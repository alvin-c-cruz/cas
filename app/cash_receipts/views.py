from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, abort, current_app
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy.orm import selectinload
from app import db
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine, CRVRevenueLine
from app.sales_invoices.models import SalesInvoice
from app.customers.models import Customer
from app.accounts.models import Account
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax
from app.audit.utils import log_create, log_update, log_audit, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.export import export_to_excel, export_to_csv
from app.settings import AppSettings
from app.periods.utils import validate_transaction_date_with_flash
from app.journal_entries.utils import generate_entry_number
from datetime import date
from decimal import Decimal, InvalidOperation
import json

cash_receipts_bp = Blueprint('cash_receipts', __name__,
                              template_folder='templates')


def accountant_or_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def staff_or_above_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


VALID_CRV_STATUSES = {'draft', 'posted', 'voided', 'cancelled'}


class CRVLineError(Exception):
    """Raised when a submitted CRV line fails server-side validation.

    Carries a user-facing message that is safe to flash (no internal/DB detail).
    """


@cash_receipts_bp.before_request
def require_branch_selection():
    if current_user.is_authenticated and not session.get('selected_branch_id'):
        flash('Please select a branch to continue.', 'warning')
        return redirect(url_for('users.select_branch'))


def generate_crv_number():
    """Plain continuous 5-digit sequence: 00001, 00002, ... No prefix, no reset.

    Independent running sequence from Sales Invoices (separate table). Each CRV gets
    the next number after the highest existing purely-numeric crv_number; legacy
    prefixed numbers (e.g. 'CR-2026-06-0007') are ignored.
    """
    rows = CashReceiptVoucher.query.with_entities(CashReceiptVoucher.crv_number).all()
    nums = [int(r[0]) for r in rows if r[0] and r[0].isdigit()]
    next_num = (max(nums) + 1) if nums else 1
    return f'{next_num:05d}'


def _get_crv_or_404(id):
    crv = CashReceiptVoucher.query.get_or_404(id)
    if crv.branch_id != session.get('selected_branch_id'):
        abort(404)
    return crv


def _get_gl_accounts():
    """Return AR-Trade (10201) and Creditable WHT Receivable (10212) accounts."""
    return {
        'ar': Account.query.filter_by(code='10201').first(),
        'wt': Account.query.filter_by(code='10212').first(),
    }


def _get_all_accounts_for_select():
    all_accts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in all_accts if a.parent_id is not None}
    id_map = {a.id: a for a in all_accts}

    def _depth(acct):
        d, p = 0, acct.parent_id
        while p and p in id_map:
            d += 1
            p = id_map[p].parent_id
        return d

    result = []
    for a in all_accts:
        d = a.to_dict()
        d['is_group'] = a.id in parent_ids
        d['depth'] = _depth(a)
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# VAT / accounting helpers
# ---------------------------------------------------------------------------

def _output_vat_buckets(crv):
    """Group output VAT by VATCategory.output_vat_account. Raises if a VAT-bearing
    revenue line's category has no output account."""
    if Decimal(str(crv.total_vat)) == 0:
        return []
    categories = {c.code: c for c in SalesVATCategory.query.all()}
    buckets = {}
    for line in crv.revenue_lines:
        vat_amt = Decimal(str(line.vat_amount or 0))
        if vat_amt <= 0:
            continue
        cat = categories.get(line.vat_category)
        acct = cat.output_vat_account if cat else None
        if acct is None:
            label = cat.code if cat else (line.vat_category or 'unknown')
            raise ValueError(
                f"VAT category '{label}' has no Output Tax account configured. "
                "Set it in VAT Categories before posting.")
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += vat_amt
    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    total = sum((amt for _, amt in ordered), Decimal('0.00'))
    override_diff = Decimal(str(crv.total_vat)) - total
    if override_diff != Decimal('0.00') and ordered:
        largest_id = max(ordered, key=lambda b: b[1])[0].id
        ordered = [
            (acct, amt + override_diff if acct.id == largest_id else amt)
            for acct, amt in ordered
        ]
    ordered = [(acct, amt) for acct, amt in ordered if amt != Decimal('0.00')]
    if any(amt < Decimal('0.00') for _, amt in ordered):
        raise ValueError('VAT override is too far below computed VAT to allocate.')
    return ordered


def _post_crv_je(crv, user_id):
    """Create the receipt JE: Cr AR + Cr Revenue + Cr Output VAT; Dr WHT Recv + Dr Cash."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    accts = _get_gl_accounts()
    ar_account = accts['ar']
    if not ar_account:
        raise ValueError("Accounts Receivable - Trade (10201) not found in COA.")
    cash_account = crv.cash_account
    if not cash_account:
        raise ValueError("Cash/Bank account not set on the receipt.")

    wt_account = None
    if crv.total_wt and Decimal(str(crv.total_wt)) > 0:
        wt_account = accts['wt']
        if not wt_account:
            raise ValueError("Creditable Withholding Tax (10212) not found in COA.")

    je_status = 'posted' if crv.status == 'posted' else 'draft'
    je = JournalEntry(
        entry_number=generate_entry_number(crv.branch_id),
        entry_date=crv.crv_date,
        description=f'CR {crv.crv_number} — {crv.customer_name}',
        reference=crv.crv_number,
        entry_type='receipt',
        branch_id=crv.branch_id,
        created_by_id=user_id,
        status=je_status,
        posted_by_id=user_id if je_status == 'posted' else None,
        posted_at=ph_now() if je_status == 'posted' else None,
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00'),
    )
    db.session.add(je)
    db.session.flush()

    line_num = 1
    first_revenue_line = None
    all_lines = []

    # Credit: AR per applied invoice
    for ar_line in crv.ar_lines:
        jl = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=ar_account.id,
            description=f'AR Collection: {ar_line.invoice_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=Decimal(str(ar_line.amount_applied)))
        db.session.add(jl); all_lines.append(jl); line_num += 1

    # Credit: revenue (net base) per direct revenue line
    for rl in crv.revenue_lines:
        if not rl.account_id:
            continue
        net_base = Decimal(str(rl.line_total)) - Decimal(str(rl.vat_amount))
        jl = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=rl.account_id,
            description=rl.description or '',
            debit_amount=Decimal('0.00'), credit_amount=net_base)
        db.session.add(jl); all_lines.append(jl)
        if first_revenue_line is None:
            first_revenue_line = jl
        line_num += 1

    # Credit: output VAT buckets
    for vat_acct, vat_amt in _output_vat_buckets(crv):
        if vat_amt <= 0:
            continue
        jl = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=vat_acct.id,
            description=f'Output VAT: {crv.crv_number}',
            debit_amount=Decimal('0.00'), credit_amount=vat_amt)
        db.session.add(jl); all_lines.append(jl); line_num += 1

    # Debit: Creditable WHT Receivable
    if wt_account and Decimal(str(crv.total_wt)) > 0:
        jl = JournalEntryLine(
            entry_id=je.id, line_number=line_num, account_id=wt_account.id,
            description=f'Creditable WHT: {crv.crv_number}',
            debit_amount=Decimal(str(crv.total_wt)), credit_amount=Decimal('0.00'))
        db.session.add(jl); all_lines.append(jl); line_num += 1

    # Debit: Cash/Bank
    cash_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num, account_id=cash_account.id,
        description=f'CR {crv.crv_number} — {crv.customer_name}',
        debit_amount=Decimal(str(crv.total_amount)), credit_amount=Decimal('0.00'))
    db.session.add(cash_line); all_lines.append(cash_line)

    sum_debits = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_credits = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    residual = sum_debits - sum_credits
    if residual != Decimal('0.00') and first_revenue_line is not None:
        first_revenue_line.credit_amount += residual

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"CRV JE is not balanced (debit={je.total_debit}, credit={je.total_credit}). "
            "Ensure every revenue line has a revenue account assigned.")
    return je


def _create_crv_reversal_je(crv, reversal_date, user_id):
    """Swap all debits/credits from the CRV's original JE."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    source_je = crv.journal_entry
    if source_je is None:
        raise ValueError(f'CRV {crv.crv_number} has no journal entry to reverse.')

    entry_number = generate_entry_number(crv.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'CRV Cancel — {crv.crv_number} (reversal)',
        reference=f'CANCEL-{crv.crv_number}',
        entry_type='reversal',
        is_reversing=True,
        reversed_entry_id=source_je.id,
        branch_id=crv.branch_id,
        created_by_id=user_id,
        status='posted',
        posted_by_id=user_id,
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00')
    )
    db.session.add(je)
    db.session.flush()

    for i, src in enumerate(source_je.lines.all(), start=1):
        rev = JournalEntryLine(
            entry_id=je.id, line_number=i,
            account_id=src.account_id,
            description=f'Cancel: {src.description}',
            debit_amount=src.credit_amount,
            credit_amount=src.debit_amount
        )
        db.session.add(rev)

    db.session.flush()
    je.calculate_totals()
    return je


def _build_crv_je_preview(crv):
    """Return [{code, name, debit, credit}] for the JE section on the detail page.

    If the CRV has a stored JE, read from it.
    If draft (no stored JE), compute what _post_crv_je would produce.
    """
    if crv.journal_entry:
        return [
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in crv.journal_entry.lines.all()
        ]

    # Draft preview: compute inline (mirrors _post_crv_je structure)
    accts = _get_gl_accounts()
    entries = []

    # Credit: AR per applied invoice
    for ar_line in crv.ar_lines:
        if accts['ar']:
            entries.append({'code': accts['ar'].code, 'name': accts['ar'].name,
                            'debit': Decimal('0.00'),
                            'credit': Decimal(str(ar_line.amount_applied))})

    # Credit: revenue (net base) per direct revenue line
    for rl in crv.revenue_lines:
        if not rl.account_id or not rl.account:
            continue
        net_base = Decimal(str(rl.line_total)) - Decimal(str(rl.vat_amount))
        entries.append({'code': rl.account.code, 'name': rl.account.name,
                        'debit': Decimal('0.00'), 'credit': net_base})

    # Credit: output VAT buckets
    try:
        vat_buckets = _output_vat_buckets(crv)
    except ValueError as e:
        vat_buckets = []
        vat_amount = Decimal(str(crv.total_vat))
        if vat_amount > 0:
            entries.append({'code': '—', 'name': str(e),
                            'debit': Decimal('0.00'), 'credit': vat_amount})

    for vat_acct, vat_amt in vat_buckets:
        if vat_amt <= 0:
            continue
        entries.append({'code': vat_acct.code, 'name': vat_acct.name,
                        'debit': Decimal('0.00'), 'credit': vat_amt})

    # Debit: Creditable WHT Receivable
    if crv.total_wt and Decimal(str(crv.total_wt)) > 0 and accts['wt']:
        entries.append({'code': accts['wt'].code, 'name': accts['wt'].name,
                        'debit': Decimal(str(crv.total_wt)), 'credit': Decimal('0.00')})

    # Debit: Cash/Bank
    if crv.cash_account:
        entries.append({'code': crv.cash_account.code, 'name': crv.cash_account.name,
                        'debit': Decimal(str(crv.total_amount)), 'credit': Decimal('0.00')})

    return entries


# ---------------------------------------------------------------------------
# Import form
# ---------------------------------------------------------------------------
from app.cash_receipts.forms import CashReceiptForm


# ---------------------------------------------------------------------------
# Override helpers
# ---------------------------------------------------------------------------

def _apply_crv_overrides(crv):
    """Apply VAT/WT manual overrides from request.form to crv."""
    import decimal as _decimal
    vat_override = request.form.get('vat_override') == '1'
    wt_override = request.form.get('wt_override') == '1'
    crv.vat_override = vat_override
    crv.wt_override = wt_override
    if vat_override:
        try:
            vat_val = Decimal(request.form.get('vat_override_value', '0') or '0')
            if vat_val < 0:
                raise ValueError('negative')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid VAT override value.', 'danger')
            return redirect(url_for('cash_receipts.list_crvs'))
        crv.total_vat = vat_val
    if wt_override:
        try:
            wt_val = Decimal(request.form.get('wt_override_value', '0') or '0')
            if wt_val < 0:
                raise ValueError('negative')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid WHT override value.', 'danger')
            return redirect(url_for('cash_receipts.list_crvs'))
        crv.total_wt = wt_val
    crv.total_amount = crv.total_ar_applied + crv.total_revenue - crv.total_wt
    return None


def _apply_ar_collections(crv):
    """Increase invoice amount_paid and reduce balance on CRV post."""
    for ar_line in crv.ar_lines:
        inv = ar_line.sales_invoice
        amount_applied = Decimal(str(ar_line.amount_applied))
        current_balance = Decimal(str(inv.balance))
        if amount_applied > current_balance:
            raise ValueError(
                f'Cannot post: collection on {ar_line.invoice_number} ({amount_applied}) '
                f'exceeds its current open balance ({current_balance}).')
        inv.amount_paid = Decimal(str(inv.amount_paid)) + amount_applied
        inv.balance = Decimal(str(inv.total_amount)) - inv.amount_paid
        if inv.balance <= 0:
            inv.status = 'paid'
        elif inv.amount_paid > 0:
            inv.status = 'partially_paid'


def _reverse_ar_collections(crv):
    """Reverse invoice amounts on CRV cancel. Raises ValueError on inconsistency."""
    for ar_line in crv.ar_lines:
        inv = ar_line.sales_invoice
        new_paid = Decimal(str(inv.amount_paid)) - Decimal(str(ar_line.amount_applied))
        if new_paid < 0:
            raise ValueError(
                f'Cannot cancel: reversing collection on {ar_line.invoice_number} '
                f'would result in negative amount_paid.')
        inv.amount_paid = new_paid
        inv.balance = Decimal(str(inv.total_amount)) - new_paid
        if inv.status in ('paid', 'partially_paid'):
            inv.status = 'posted' if inv.amount_paid <= 0 else 'partially_paid'


# ---------------------------------------------------------------------------
# Open invoices JSON endpoint
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts/open-invoices')
@login_required
@staff_or_above_required
def open_invoices():
    """JSON list of open sales invoices for a customer in the current branch."""
    customer_id = request.args.get('customer_id', type=int)
    if not customer_id:
        return jsonify([])
    branch_id = session.get('selected_branch_id')
    invs = SalesInvoice.query.filter(
        SalesInvoice.branch_id == branch_id,
        SalesInvoice.customer_id == customer_id,
        SalesInvoice.status.in_(['posted', 'partially_paid']),
        SalesInvoice.balance > 0,
    ).order_by(SalesInvoice.invoice_date).all()
    return jsonify([{
        'id': i.id,
        'invoice_number': i.invoice_number,
        'invoice_date': i.invoice_date.isoformat(),
        'due_date': i.due_date.isoformat() if i.due_date else None,
        'balance': float(i.balance),
    } for i in invs])


# ---------------------------------------------------------------------------
# Line-item parsing
# ---------------------------------------------------------------------------

def _parse_line_items(crv):
    ar_lines_data = request.form.getlist('ar_lines')
    ar_lines = json.loads(ar_lines_data[0]) if ar_lines_data and ar_lines_data[0] else []
    for idx, item in enumerate(ar_lines, start=1):
        try:
            invoice_id = int(item['invoice_id'])
            amount_applied = Decimal(str(item['amount_applied']))
        except (KeyError, ValueError, TypeError, InvalidOperation):
            raise CRVLineError('An AR line is malformed — please re-select the invoice and try again.')
        inv = SalesInvoice.query.filter_by(
            id=invoice_id, branch_id=crv.branch_id, customer_id=crv.customer_id
        ).first()
        if not inv:
            raise CRVLineError('A selected invoice is not available for this customer and branch.')
        if amount_applied <= 0 or amount_applied > inv.balance:
            raise CRVLineError(
                f'Amount to collect for {inv.invoice_number} must be between 0.01 and the '
                f'open balance ({inv.balance:,.2f}).'
            )
        crv.ar_lines.append(CRVArLine(
            line_number=idx,
            invoice_id=inv.id,
            invoice_number=inv.invoice_number,
            original_balance=inv.balance,
            amount_applied=amount_applied,
        ))

    revenue_lines_data = request.form.getlist('revenue_lines')
    revenue_lines = json.loads(revenue_lines_data[0]) if revenue_lines_data and revenue_lines_data[0] else []
    leaf_account_ids = {a['id'] for a in _get_all_accounts_for_select() if not a['is_group']}
    for idx, item in enumerate(revenue_lines, start=1):
        try:
            amount = Decimal(str(item.get('amount', 0)))
        except (ValueError, TypeError, InvalidOperation):
            raise CRVLineError('A revenue line amount is invalid.')
        account_id = int(item['account_id']) if item.get('account_id') else None
        if account_id not in leaf_account_ids:
            raise CRVLineError('Each revenue line must use a valid, postable account.')
        vat_rate = Decimal('0.00')
        vat_category = item.get('vat_category')
        if vat_category:
            vat_cat = SalesVATCategory.query.filter_by(code=vat_category, is_active=True).first()
            if vat_cat:
                vat_rate = Decimal(str(vat_cat.rate))
        wt_id = int(item['wt_id']) if item.get('wt_id') else None
        wt_rate = None
        if wt_id:
            wt_obj = WithholdingTax.query.get(wt_id)
            if wt_obj:
                wt_rate = wt_obj.rate
        rev_line = CRVRevenueLine(
            line_number=idx,
            description=item.get('description', ''),
            amount=amount,
            vat_category=vat_category,
            vat_rate=vat_rate,
            account_id=account_id,
            wt_id=wt_id,
            wt_rate=wt_rate,
        )
        rev_line.calculate_amounts()
        crv.revenue_lines.append(rev_line)


# ---------------------------------------------------------------------------
# Form context helper
# ---------------------------------------------------------------------------

def _form_context(all_accounts=None):
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    if all_accounts is None:
        all_accounts = _get_all_accounts_for_select()
    vat_categories = [v.to_dict() for v in SalesVATCategory.query.filter_by(is_active=True).order_by(SalesVATCategory.code).all()]
    _accts = _get_gl_accounts()
    gl_accounts = {
        'ar': {'code': _accts['ar'].code, 'name': _accts['ar'].name} if _accts['ar'] else None,
        'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
    }
    all_whts = [w.to_dict() for w in WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()]
    return dict(customers=customers, all_accounts=all_accounts,
                vat_categories=vat_categories,
                all_whts=all_whts,
                gl_accounts=gl_accounts)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts')
@login_required
def list_crvs():
    from app.cash_receipts.utils import compute_crv_summary
    page = request.args.get('page', 1, type=int)
    per_page = 50
    branch_id = session.get('selected_branch_id')
    query = CashReceiptVoucher.query.filter_by(branch_id=branch_id)

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_CRV_STATUSES:
        query = query.filter_by(status=status_filter)

    customer_filter = request.args.get('customer', 'all')
    if customer_filter != 'all':
        try:
            query = query.filter_by(customer_id=int(customer_filter))
        except ValueError:
            pass

    q = request.args.get('q', '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            CashReceiptVoucher.crv_number.ilike(like),
            CashReceiptVoucher.customer_name.ilike(like)
        ))

    year = ph_now().year
    date_from = request.args.get('date_from', f'{year}-01-01')
    if date_from:
        try:
            query = query.filter(CashReceiptVoucher.crv_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', f'{year}-12-31')
    if date_to:
        try:
            query = query.filter(CashReceiptVoucher.crv_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    pm_filter = request.args.get('payment_method', 'all')
    if pm_filter != 'all':
        query = query.filter_by(payment_method=pm_filter)

    query = query.order_by(CashReceiptVoucher.crv_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    summary = compute_crv_summary(branch_id)
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    return render_template('cash_receipts/list.html',
                           crvs=pagination.items,
                           pagination=pagination,
                           customers=customers,
                           summary=summary,
                           today=ph_now().date(),
                           status_filter=status_filter,
                           customer_filter=customer_filter,
                           q=q,
                           date_from=date_from,
                           date_to=date_to,
                           pm_filter=pm_filter)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    form = CashReceiptForm()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.code).all()
    form.customer_id.choices = [(c.id, f'{c.code} - {c.name}') for c in customers]
    all_accounts = _get_all_accounts_for_select()
    form.cash_account_id.choices = [(0, '-- Select Account --')] + [
        (a['id'], f"{a['code']} — {a['name']}") for a in all_accounts if not a['is_group']
    ]

    def _render_form():
        is_post = request.method == 'POST'
        return render_template('cash_receipts/form.html', form=form, crv=None,
                               restore_ar_lines=request.form.get('ar_lines', '') if is_post else '',
                               restore_revenue_lines=request.form.get('revenue_lines', '') if is_post else '',
                               **_form_context(all_accounts=all_accounts))

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.crv_date.data, 'Cash Receipt Voucher'):
            return _render_form()
        try:
            customer = Customer.query.get(form.customer_id.data)
            if not customer:
                flash('Selected customer not found.', 'error')
                return _render_form()

            crv = CashReceiptVoucher(
                branch_id=session.get('selected_branch_id'),
                crv_number=generate_crv_number(),
                crv_date=form.crv_date.data,
                customer_id=customer.id,
                customer_name=customer.name,
                customer_tin=customer.tin,
                payment_method=form.payment_method.data,
                check_number=form.check_number.data or None,
                check_date=form.check_date.data or None,
                check_bank=form.check_bank.data or None,
                cash_account_id=form.cash_account_id.data,
                notes=form.notes.data,
                status='draft',
                created_by_id=current_user.id
            )
            _parse_line_items(crv)
            crv.calculate_totals()
            err = _apply_crv_overrides(crv)
            if err:
                return err

            db.session.add(crv)
            db.session.flush()

            je = _post_crv_je(crv, current_user.id)
            crv.journal_entry_id = je.id
            db.session.commit()

            log_create(
                module='cash_receipt',
                record_id=crv.id,
                record_identifier=f'{crv.crv_number} - {crv.customer_name}',
                new_values=model_to_dict(crv, ['crv_number', 'crv_date', 'customer_name',
                                               'payment_method', 'total_amount', 'status'])
            )
            flash(f'CRV "{crv.crv_number}" entered successfully!', 'success')
            return redirect(url_for('cash_receipts.view', id=crv.id))

        except CRVLineError as ce:
            db.session.rollback()
            flash(str(ce), 'error')
            return _render_form()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating CRV', exc_info=True)
            log_exception(e, severity='ERROR', module='cash_receipts.create')
            flash('An unexpected error occurred while entering the CRV. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    if request.method == 'GET':
        form.crv_number.data = generate_crv_number()
        form.crv_date.data = ph_now().date()

    return _render_form()


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit(id):
    crv = _get_crv_or_404(id)
    if crv.status != 'draft':
        flash('Only draft CRVs can be edited.', 'error')
        return redirect(url_for('cash_receipts.view', id=id))

    form = CashReceiptForm(obj=crv)
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.code).all()
    form.customer_id.choices = [(c.id, f'{c.code} - {c.name}') for c in customers]
    all_accounts = _get_all_accounts_for_select()
    form.cash_account_id.choices = [
        (a['id'], f"{a['code']} — {a['name']}") for a in all_accounts if not a['is_group']
    ]

    tmpl_ar_lines = [l.to_dict() for l in crv.ar_lines]
    tmpl_revenue_lines = [l.to_dict() for l in crv.revenue_lines]

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.crv_date.data, 'Cash Receipt Voucher'):
            ctx = _form_context(all_accounts=all_accounts)
            return render_template('cash_receipts/form.html', form=form, crv=crv,
                                   ar_lines=tmpl_ar_lines, revenue_lines=tmpl_revenue_lines, **ctx)
        try:
            customer = Customer.query.get(form.customer_id.data)
            if not customer:
                flash('Selected customer not found.', 'error')
                ctx = _form_context(all_accounts=all_accounts)
                return render_template('cash_receipts/form.html', form=form, crv=crv,
                                       ar_lines=tmpl_ar_lines, revenue_lines=tmpl_revenue_lines, **ctx)

            crv.crv_date = form.crv_date.data
            crv.customer_id = customer.id
            crv.customer_name = customer.name
            crv.customer_tin = customer.tin
            crv.payment_method = form.payment_method.data
            crv.check_number = form.check_number.data or None
            crv.check_date = form.check_date.data or None
            crv.check_bank = form.check_bank.data or None
            crv.cash_account_id = form.cash_account_id.data
            crv.notes = form.notes.data

            for ar in list(crv.ar_lines):
                db.session.delete(ar)
            for rev in list(crv.revenue_lines):
                db.session.delete(rev)
            crv.ar_lines = []
            crv.revenue_lines = []
            db.session.flush()

            _parse_line_items(crv)
            crv.calculate_totals()
            err = _apply_crv_overrides(crv)
            if err:
                return err

            if crv.journal_entry_id:
                from app.journal_entries.models import JournalEntry as _JE
                old_je = db.session.get(_JE, crv.journal_entry_id)
                crv.journal_entry_id = None
                crv.journal_entry = None
                db.session.flush()
                if old_je:
                    db.session.delete(old_je)
                db.session.flush()

            je = _post_crv_je(crv, current_user.id)
            crv.journal_entry_id = je.id
            db.session.commit()

            log_update(
                module='cash_receipt',
                record_id=crv.id,
                record_identifier=f'{crv.crv_number} - {crv.customer_name}',
                old_values={}, new_values={}
            )
            flash(f'CRV "{crv.crv_number}" updated successfully!', 'success')
            return redirect(url_for('cash_receipts.view', id=crv.id))

        except CRVLineError as ce:
            db.session.rollback()
            flash(str(ce), 'error')
            ctx = _form_context(all_accounts=all_accounts)
            return render_template('cash_receipts/form.html', form=form, crv=crv,
                                   ar_lines=tmpl_ar_lines, revenue_lines=tmpl_revenue_lines, **ctx)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error editing CRV', exc_info=True)
            log_exception(e, severity='ERROR', module='cash_receipts.edit')
            flash('An unexpected error occurred while updating the CRV. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    ctx = _form_context(all_accounts=all_accounts)
    return render_template('cash_receipts/form.html', form=form, crv=crv,
                           ar_lines=tmpl_ar_lines, revenue_lines=tmpl_revenue_lines, **ctx)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts/<int:id>')
@login_required
def view(id):
    crv = _get_crv_or_404(id)
    je_entries = _build_crv_je_preview(crv)
    cr_print_access = AppSettings.get_setting('cr_print_access', 'posted_only')
    return render_template('cash_receipts/detail.html',
                           crv=crv, je_entries=je_entries, now=ph_now(),
                           cr_print_access=cr_print_access)


# ---------------------------------------------------------------------------
# Post
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post(id):
    crv = _get_crv_or_404(id)
    if crv.status != 'draft':
        flash('Only draft CRVs can be posted.', 'error')
        return redirect(url_for('cash_receipts.view', id=id))
    if not validate_transaction_date_with_flash(crv.crv_date, 'Cash Receipt'):
        return redirect(url_for('cash_receipts.view', id=id))
    try:
        crv.status = 'posted'
        crv.posted_by_id = current_user.id
        crv.posted_at = ph_now()
        if crv.journal_entry:
            crv.journal_entry.status = 'posted'
            crv.journal_entry.posted_by_id = current_user.id
            crv.journal_entry.posted_at = ph_now()
        _apply_ar_collections(crv)
        db.session.commit()
        log_audit(
            module='cash_receipt', action='post',
            record_id=crv.id,
            record_identifier=f'{crv.crv_number} - {crv.customer_name}',
            notes=f'Posted by {current_user.username}'
        )
        flash(f'CRV "{crv.crv_number}" posted successfully!', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error posting CRV', exc_info=True)
        log_exception(e, severity='ERROR', module='cash_receipts.post')
        flash('An unexpected error occurred while posting the CRV. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('cash_receipts.view', id=id))


# ---------------------------------------------------------------------------
# Void
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts/<int:id>/void', methods=['POST'])
@login_required
@staff_or_above_required
def void(id):
    crv = _get_crv_or_404(id)
    if crv.status != 'draft':
        flash('Only draft CRVs can be voided.', 'error')
        return redirect(url_for('cash_receipts.view', id=id))
    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('cash_receipts.view', id=id))
    try:
        if crv.journal_entry_id:
            from app.journal_entries.models import JournalEntry as _JE
            je_to_delete = db.session.get(_JE, crv.journal_entry_id)
            if je_to_delete:
                db.session.delete(je_to_delete)
            crv.journal_entry_id = None
            crv.journal_entry = None
        crv.status = 'voided'
        crv.voided_at = ph_now()
        crv.voided_by_id = current_user.id
        crv.void_reason = void_reason
        db.session.commit()
        log_audit(
            module='cash_receipt', action='void',
            record_id=crv.id,
            record_identifier=f'{crv.crv_number} - {crv.customer_name}',
            notes=f'Voided by {current_user.username}. Reason: {void_reason}'
        )
        flash(f'CRV "{crv.crv_number}" voided.', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error voiding CRV', exc_info=True)
        log_exception(e, severity='ERROR', module='cash_receipts.void')
        flash('An unexpected error occurred while voiding the CRV. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('cash_receipts.view', id=id))


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    crv = _get_crv_or_404(id)
    if crv.status != 'posted':
        flash('Only posted CRVs can be cancelled.', 'error')
        return redirect(url_for('cash_receipts.view', id=id))
    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Cancellation reason must be at least 10 characters.', 'error')
        return redirect(url_for('cash_receipts.view', id=id))
    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('cash_receipts.view', id=id))
    try:
        _reverse_ar_collections(crv)
        _create_crv_reversal_je(crv, reversal_date, current_user.id)
        crv.status = 'cancelled'
        crv.cancelled_at = ph_now()
        crv.cancel_reason = cancel_reason
        db.session.commit()
        log_audit(
            module='cash_receipt', action='cancel',
            record_id=crv.id,
            record_identifier=f'{crv.crv_number} - {crv.customer_name}',
            notes=f'Cancelled by {current_user.username}. Reason: {cancel_reason}'
        )
        flash(f'CRV "{crv.crv_number}" cancelled. Reversal JE created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error cancelling CRV', exc_info=True)
        log_exception(e, severity='ERROR', module='cash_receipts.cancel')
        flash('An unexpected error occurred while cancelling the CRV. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('cash_receipts.view', id=id))


# ---------------------------------------------------------------------------
# Print
# ---------------------------------------------------------------------------

@cash_receipts_bp.route('/cash-receipts/<int:id>/print')
@login_required
def print_crv(id):
    crv = _get_crv_or_404(id)
    je_entries = _build_crv_je_preview(crv)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('cash_receipts/print.html',
                           crv=crv, je_entries=je_entries,
                           company=company, printed_at=ph_now())


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _crv_export_data(branch_id):
    q = CashReceiptVoucher.query.filter_by(branch_id=branch_id)

    status = request.args.get('status', '')
    customer_id = request.args.get('customer', '')
    payment_method = request.args.get('payment_method', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    if status and status != 'all':
        q = q.filter(CashReceiptVoucher.status == status)
    if customer_id and customer_id != 'all':
        try:
            q = q.filter(CashReceiptVoucher.customer_id == int(customer_id))
        except ValueError:
            pass
    if payment_method and payment_method != 'all':
        q = q.filter(CashReceiptVoucher.payment_method == payment_method)
    if date_from:
        try:
            q = q.filter(CashReceiptVoucher.crv_date >= date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(CashReceiptVoucher.crv_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    crvs = q.order_by(CashReceiptVoucher.crv_date.desc(),
                      CashReceiptVoucher.crv_number.desc()).all()

    columns = [
        'CRV Number', 'Date', 'Customer', 'Payment Method',
        'Check #', 'Check Date', 'Cash/Bank Account',
        'AR Applied', 'Direct Revenue', 'Output VAT', 'WHT',
        'Net Received', 'Status',
    ]
    data = []
    for crv in crvs:
        data.append({
            'CRV Number': crv.crv_number,
            'Date': crv.crv_date.strftime('%Y-%m-%d') if crv.crv_date else '',
            'Customer': crv.customer_name,
            'Payment Method': (crv.payment_method.replace('_', ' ').title()
                               if crv.payment_method else ''),
            'Check #': crv.check_number or '',
            'Check Date': crv.check_date.strftime('%Y-%m-%d') if crv.check_date else '',
            'Cash/Bank Account': (
                f'{crv.cash_account.code} — {crv.cash_account.name}'
                if crv.cash_account else ''
            ),
            'AR Applied': float(crv.total_ar_applied or 0),
            'Direct Revenue': float(crv.total_revenue or 0),
            'Output VAT': float(crv.total_vat or 0),
            'WHT': float(crv.total_wt or 0),
            'Net Received': float(crv.total_amount or 0),
            'Status': crv.status.title() if crv.status else '',
        })
    return data, columns, columns


@cash_receipts_bp.route('/cash-receipts/export/excel')
@login_required
def export_excel():
    branch_id = session.get('selected_branch_id')
    data, columns, headers = _crv_export_data(branch_id)
    return export_to_excel(
        data=data,
        columns=columns,
        headers=headers,
        filename=f'cash_receipts_{ph_now().strftime("%Y%m%d")}.xlsx',
        title='Cash Receipts',
    )


@cash_receipts_bp.route('/cash-receipts/export/csv')
@login_required
def export_csv():
    branch_id = session.get('selected_branch_id')
    data, columns, headers = _crv_export_data(branch_id)
    return export_to_csv(
        data=data,
        columns=columns,
        headers=headers,
        filename=f'cash_receipts_{ph_now().strftime("%Y%m%d")}.csv',
    )
