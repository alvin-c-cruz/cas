from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, abort, current_app
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy.orm import selectinload
from app import db
from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine, CDVExpenseLine
from app.cash_disbursements.forms import CashDisbursementForm
from app.accounts_payable.models import AccountsPayable
from app.vendors.models import Vendor
from app.vendors.forms import VendorForm
from app.vendors.utils import populate_vat_category_choices, generate_next_vendor_code
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
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

cash_disbursements_bp = Blueprint('cash_disbursements', __name__,
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


VALID_CDV_STATUSES = {'draft', 'posted', 'voided', 'cancelled'}


class CDVLineError(Exception):
    """Raised when a submitted CDV line fails server-side validation.

    Carries a user-facing message that is safe to flash (no internal/DB detail).
    """


@cash_disbursements_bp.before_request
def require_branch_selection():
    if current_user.is_authenticated and not session.get('selected_branch_id'):
        flash('Please select a branch to continue.', 'warning')
        return redirect(url_for('users.select_branch'))


def generate_cdv_number():
    """Generate next CDV number: CD-YYYY-MM-NNNN, sequential per month."""
    now = ph_now()
    prefix = f'CD-{now.year}-{now.month:02d}-'
    latest = CashDisbursementVoucher.query.filter(
        CashDisbursementVoucher.cdv_number.like(f'{prefix}%')
    ).order_by(CashDisbursementVoucher.cdv_number.desc()).first()
    if latest:
        try:
            last_num = int(latest.cdv_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    return f'{prefix}{next_num:04d}'


def _get_cdv_or_404(id):
    cdv = CashDisbursementVoucher.query.get_or_404(id)
    if cdv.branch_id != session.get('selected_branch_id'):
        abort(404)
    return cdv


def _get_gl_accounts():
    return {
        'ap': Account.query.filter_by(code='20101').first(),
        'wt': Account.query.filter_by(code='20301').first(),
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


@cash_disbursements_bp.route('/cash-disbursements')
@login_required
def list_cdvs():
    from app.cash_disbursements.utils import compute_cdv_summary
    page = request.args.get('page', 1, type=int)
    per_page = 50
    branch_id = session.get('selected_branch_id')
    query = CashDisbursementVoucher.query.filter_by(branch_id=branch_id)

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_CDV_STATUSES:
        query = query.filter_by(status=status_filter)

    vendor_filter = request.args.get('vendor', 'all')
    if vendor_filter != 'all':
        try:
            query = query.filter_by(vendor_id=int(vendor_filter))
        except ValueError:
            pass

    q = request.args.get('q', '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            CashDisbursementVoucher.cdv_number.ilike(like),
            CashDisbursementVoucher.vendor_name.ilike(like)
        ))

    year = ph_now().year
    date_from = request.args.get('date_from', f'{year}-01-01')
    if date_from:
        try:
            query = query.filter(CashDisbursementVoucher.cdv_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', f'{year}-12-31')
    if date_to:
        try:
            query = query.filter(CashDisbursementVoucher.cdv_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    pm_filter = request.args.get('payment_method', 'all')
    if pm_filter != 'all':
        query = query.filter_by(payment_method=pm_filter)

    query = query.order_by(CashDisbursementVoucher.cdv_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    summary = compute_cdv_summary(branch_id)
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('cash_disbursements/list.html',
                           cdvs=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           today=ph_now().date(),
                           status_filter=status_filter,
                           vendor_filter=vendor_filter,
                           q=q,
                           date_from=date_from,
                           date_to=date_to,
                           pm_filter=pm_filter)


@cash_disbursements_bp.route('/cash-disbursements/open-bills')
@login_required
@staff_or_above_required
def open_bills():
    """Return JSON list of open APV bills for the given vendor in the current branch."""
    vendor_id = request.args.get('vendor_id', type=int)
    if not vendor_id:
        return jsonify([])
    branch_id = session.get('selected_branch_id')
    bills = AccountsPayable.query.filter(
        AccountsPayable.branch_id == branch_id,
        AccountsPayable.vendor_id == vendor_id,
        AccountsPayable.status.in_(['posted', 'partially_paid']),
        AccountsPayable.balance > 0
    ).order_by(AccountsPayable.ap_date).all()
    return jsonify([{
        'id': b.id,
        'bill_number': b.ap_number,
        'vendor_invoice_number': b.vendor_invoice_number or '',
        'bill_date': b.ap_date.isoformat(),
        'balance': float(b.balance),
    } for b in bills])


def _cdv_input_vat_buckets(cdv):
    """Group expense lines' input VAT by VATCategory.input_vat_account."""
    if Decimal(str(cdv.total_vat)) <= 0:
        return []
    categories = {c.code: c for c in VATCategory.query.all()}
    buckets = {}
    for line in cdv.expense_lines:
        vat_amt = Decimal(str(line.vat_amount or 0))
        if vat_amt <= 0:
            continue
        cat = categories.get(line.vat_category)
        acct = cat.input_vat_account if cat else None
        if acct is None:
            label = cat.code if cat else (line.vat_category or 'unknown')
            raise ValueError(
                f"VAT category '{label}' has no Input Tax account configured.")
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += vat_amt
    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    total = sum((amt for _, amt in ordered), Decimal('0.00'))
    override_diff = Decimal(str(cdv.total_vat)) - total
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


def _post_cdv_je(cdv, user_id):
    """Create a draft or posted disbursement JE for a CDV."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    _accts = _get_gl_accounts()
    ap_account = _accts['ap']
    if not ap_account:
        raise ValueError("Accounts Payable - Trade (20101) not found in COA.")

    cash_account = cdv.cash_account
    if not cash_account:
        raise ValueError("Cash/Bank account not found.")

    wt_account = None
    if cdv.total_wt and Decimal(str(cdv.total_wt)) > 0:
        wt_account = _accts['wt']
        if not wt_account:
            raise ValueError("WHT Payable - Expanded (20301) not found in COA.")

    je_status = 'posted' if cdv.status == 'posted' else 'draft'
    entry_number = generate_entry_number(cdv.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=cdv.cdv_date,
        description=f'CD {cdv.cdv_number} — {cdv.vendor_name}',
        reference=cdv.cdv_number,
        entry_type='disbursement',
        branch_id=cdv.branch_id,
        created_by_id=user_id,
        status=je_status,
        posted_by_id=user_id if je_status == 'posted' else None,
        posted_at=ph_now() if je_status == 'posted' else None,
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00')
    )
    db.session.add(je)
    db.session.flush()

    line_num = 1
    first_expense_line = None
    all_lines = []

    for ap_line in cdv.ap_lines:
        je_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=ap_account.id,
            description=f'AP Payment: {ap_line.ap_number}',
            debit_amount=Decimal(str(ap_line.amount_applied)),
            credit_amount=Decimal('0.00')
        )
        db.session.add(je_line)
        all_lines.append(je_line)
        line_num += 1

    for exp_line in cdv.expense_lines:
        if not exp_line.account_id:
            continue
        net_base = Decimal(str(exp_line.line_total)) - Decimal(str(exp_line.vat_amount))
        je_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=exp_line.account_id,
            description=exp_line.description or '',
            debit_amount=net_base,
            credit_amount=Decimal('0.00')
        )
        db.session.add(je_line)
        all_lines.append(je_line)
        if first_expense_line is None:
            first_expense_line = je_line
        line_num += 1

    for vat_acct, vat_amt in _cdv_input_vat_buckets(cdv):
        if vat_amt <= 0:
            continue
        vat_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=vat_acct.id,
            description=f'Input VAT: {cdv.cdv_number}',
            debit_amount=vat_amt,
            credit_amount=Decimal('0.00')
        )
        db.session.add(vat_line)
        all_lines.append(vat_line)
        line_num += 1

    if wt_account and Decimal(str(cdv.total_wt)) > 0:
        wt_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_account.id,
            description=f'WHT Payable: {cdv.cdv_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=Decimal(str(cdv.total_wt))
        )
        db.session.add(wt_line)
        all_lines.append(wt_line)
        line_num += 1

    cash_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=cash_account.id,
        description=f'CD {cdv.cdv_number} — {cdv.vendor_name}',
        debit_amount=Decimal('0.00'),
        credit_amount=Decimal(str(cdv.total_amount))
    )
    db.session.add(cash_line)
    all_lines.append(cash_line)

    sum_debits = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_credits = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    residual = sum_credits - sum_debits
    if residual != Decimal('0.00') and first_expense_line is not None:
        first_expense_line.debit_amount += residual

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"CDV JE is not balanced "
            f"(debit={je.total_debit}, credit={je.total_credit}). "
            "Ensure every expense line has an account assigned."
        )
    return je


def _create_cdv_reversal_je(cdv, reversal_date, user_id):
    """Swap all debits/credits from the CDV's original JE."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    source_je = cdv.journal_entry
    if source_je is None:
        raise ValueError(f'CDV {cdv.cdv_number} has no journal entry to reverse.')

    entry_number = generate_entry_number(cdv.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'CDV Cancel — {cdv.cdv_number} (reversal)',
        reference=f'CANCEL-{cdv.cdv_number}',
        entry_type='reversal',
        is_reversing=True,
        reversed_entry_id=source_je.id,
        branch_id=cdv.branch_id,
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


def _apply_cdv_overrides(cdv):
    """Apply VAT/WT manual overrides from request.form to cdv."""
    import decimal as _decimal
    vat_override = request.form.get('vat_override') == '1'
    wt_override = request.form.get('wt_override') == '1'
    cdv.vat_override = vat_override
    cdv.wt_override = wt_override
    if vat_override:
        try:
            vat_val = Decimal(request.form.get('vat_override_value', '0') or '0')
            if vat_val < 0:
                raise ValueError('negative')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid VAT override value.', 'danger')
            return redirect(url_for('cash_disbursements.list_cdvs'))
        cdv.total_vat = vat_val
    if wt_override:
        try:
            wt_val = Decimal(request.form.get('wt_override_value', '0') or '0')
            if wt_val < 0:
                raise ValueError('negative')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid WHT override value.', 'danger')
            return redirect(url_for('cash_disbursements.list_cdvs'))
        cdv.total_wt = wt_val
    cdv.total_amount = cdv.total_ap_applied + cdv.total_expense - cdv.total_wt
    return None


def _build_cdv_je_preview(cdv):
    """Return [{code, name, debit, credit}] for the JE section on the detail page."""
    if cdv.journal_entry:
        return [
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in cdv.journal_entry.lines.all()
        ]
    accts = _get_gl_accounts()
    entries = []
    for ap_line in cdv.ap_lines:
        if accts['ap']:
            entries.append({'code': accts['ap'].code, 'name': accts['ap'].name,
                            'debit': Decimal(str(ap_line.amount_applied)), 'credit': Decimal('0.00')})
    for exp_line in cdv.expense_lines:
        if not exp_line.account_id or not exp_line.account:
            continue
        net_base = Decimal(str(exp_line.line_total)) - Decimal(str(exp_line.vat_amount))
        entries.append({'code': exp_line.account.code, 'name': exp_line.account.name,
                        'debit': net_base, 'credit': Decimal('0.00')})
    try:
        for vat_acct, vat_amt in _cdv_input_vat_buckets(cdv):
            entries.append({'code': vat_acct.code, 'name': vat_acct.name,
                            'debit': vat_amt, 'credit': Decimal('0.00')})
    except ValueError:
        pass
    if cdv.total_wt and Decimal(str(cdv.total_wt)) > 0 and accts['wt']:
        entries.append({'code': accts['wt'].code, 'name': accts['wt'].name,
                        'debit': Decimal('0.00'), 'credit': Decimal(str(cdv.total_wt))})
    if cdv.cash_account:
        entries.append({'code': cdv.cash_account.code, 'name': cdv.cash_account.name,
                        'debit': Decimal('0.00'), 'credit': Decimal(str(cdv.total_amount))})
    return entries


def _parse_line_items(cdv):
    """Parse ap_lines and expense_lines from request.form JSON. Mutates cdv in place.

    Every client-supplied reference is re-validated server-side — the AJAX bill
    loader (open_bills) is only a UI convenience, not the trust boundary:
      * AP bills must belong to THIS CDV's branch and vendor;
      * amount_applied must be within 0 < x <= the bill's open balance;
      * expense accounts must be active, postable (leaf) accounts.
    Raises CDVLineError (user-facing message) on any invalid line. Requires
    cdv.branch_id and cdv.vendor_id to already be set on the passed-in cdv.
    """
    ap_lines_data = request.form.getlist('ap_lines')
    ap_lines = json.loads(ap_lines_data[0]) if ap_lines_data and ap_lines_data[0] else []
    for idx, item in enumerate(ap_lines, start=1):
        try:
            bill_id = int(item['bill_id'])
            amount_applied = Decimal(str(item['amount_applied']))
        except (KeyError, ValueError, TypeError, InvalidOperation):
            raise CDVLineError('A payable line is malformed — please re-select the bill and try again.')
        # F-001: re-scope the bill to this branch + vendor; never trust the raw id.
        bill = AccountsPayable.query.filter_by(
            id=bill_id, branch_id=cdv.branch_id, vendor_id=cdv.vendor_id
        ).first()
        if not bill:
            raise CDVLineError('A selected bill is not available for this vendor and branch.')
        # F-005: amount must be positive and within the open balance.
        if amount_applied <= 0 or amount_applied > bill.balance:
            raise CDVLineError(
                f'Amount to pay for {bill.ap_number} must be between 0.01 and the '
                f'open balance ({bill.balance:,.2f}).'
            )
        cdv.ap_lines.append(CDVApLine(
            line_number=idx,
            ap_id=bill.id,
            ap_number=bill.ap_number,
            original_balance=bill.balance,
            amount_applied=amount_applied,
        ))

    exp_lines_data = request.form.getlist('expense_lines')
    exp_lines = json.loads(exp_lines_data[0]) if exp_lines_data and exp_lines_data[0] else []
    # F-006: only active, postable (leaf) accounts may receive an expense line.
    leaf_account_ids = {a['id'] for a in _get_all_accounts_for_select() if not a['is_group']}
    for idx, item in enumerate(exp_lines, start=1):
        try:
            amount = Decimal(str(item.get('amount', 0)))
        except (ValueError, TypeError, InvalidOperation):
            raise CDVLineError('An expense line amount is invalid.')
        account_id = int(item['account_id']) if item.get('account_id') else None
        if account_id not in leaf_account_ids:
            raise CDVLineError('Each expense line must use a valid, postable account.')
        vat_rate = Decimal('0.00')
        vat_category = item.get('vat_category')
        if vat_category:
            vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
            if vat_cat:
                vat_rate = Decimal(str(vat_cat.rate))
        wt_id = int(item['wt_id']) if item.get('wt_id') else None
        wt_rate = None
        if wt_id:
            wt_obj = WithholdingTax.query.get(wt_id)
            if wt_obj:
                wt_rate = wt_obj.rate
        exp_line = CDVExpenseLine(
            line_number=idx,
            description=item.get('description', ''),
            amount=amount,
            vat_category=vat_category,
            vat_rate=vat_rate,
            account_id=account_id,
            wt_id=wt_id,
            wt_rate=wt_rate,
        )
        exp_line.calculate_amounts()
        cdv.expense_lines.append(exp_line)


def _form_context(all_accounts=None):
    """Shared context for create/edit form rendering.

    Pass the already-built `all_accounts` list (callers need it for the cash /
    expense account selects) so the hierarchy isn't recomputed a second time.
    """
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    if all_accounts is None:
        all_accounts = _get_all_accounts_for_select()
    vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
    wt_codes = [w.to_dict() for w in WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()]
    _accts = _get_gl_accounts()
    gl_accounts = {
        'ap': {'code': _accts['ap'].code, 'name': _accts['ap'].name} if _accts['ap'] else None,
        'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
    }
    quick_add_form = VendorForm()
    populate_vat_category_choices(quick_add_form)
    quick_add_form.code.data = generate_next_vendor_code()
    quick_add_form.is_active.data = '1'
    quick_add_form.payment_terms.data = 'Net 30'
    quick_add_whts = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()
    return dict(vendors=vendors, all_accounts=all_accounts,
                vat_categories=vat_categories, wt_codes=wt_codes,
                gl_accounts=gl_accounts,
                vendor_quick_add_form=quick_add_form,
                vendor_quick_add_whts=quick_add_whts)


@cash_disbursements_bp.route('/cash-disbursements/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    form = CashDisbursementForm()
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.code).all()
    form.vendor_id.choices = [(v.id, f'{v.code} - {v.name}') for v in vendors]
    all_accounts = _get_all_accounts_for_select()
    form.cash_account_id.choices = [(0, '-- Select Account --')] + [
        (a['id'], f"{a['code']} — {a['name']}") for a in all_accounts if not a['is_group']
    ]

    def _render_form():
        """Render the create form. On a failed POST, carry the submitted AP/expense
        lines back so they aren't wiped."""
        is_post = request.method == 'POST'
        return render_template('cash_disbursements/form.html', form=form, cdv=None,
                               restore_ap_lines=request.form.get('ap_lines', '') if is_post else '',
                               restore_expense_lines=request.form.get('expense_lines', '') if is_post else '',
                               **_form_context(all_accounts=all_accounts))

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.cdv_date.data, 'Cash Disbursement Voucher'):
            return _render_form()
        try:
            vendor = Vendor.query.get(form.vendor_id.data)
            if not vendor:
                flash('Selected vendor not found.', 'error')
                return _render_form()

            cdv = CashDisbursementVoucher(
                branch_id=session.get('selected_branch_id'),
                # F-007: regenerate server-side; the read-only form value is never trusted.
                cdv_number=generate_cdv_number(),
                cdv_date=form.cdv_date.data,
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                vendor_tin=vendor.tin,
                payment_method=form.payment_method.data,
                check_number=form.check_number.data or None,
                check_date=form.check_date.data or None,
                check_bank=form.check_bank.data or None,
                cash_account_id=form.cash_account_id.data,
                notes=form.notes.data,
                status='draft',
                created_by_id=current_user.id
            )
            _parse_line_items(cdv)
            cdv.calculate_totals()
            err = _apply_cdv_overrides(cdv)
            if err:
                return err

            db.session.add(cdv)
            db.session.flush()

            je = _post_cdv_je(cdv, current_user.id)
            cdv.journal_entry_id = je.id
            db.session.commit()

            log_create(
                module='cash_disbursement',
                record_id=cdv.id,
                record_identifier=f'{cdv.cdv_number} - {cdv.vendor_name}',
                new_values=model_to_dict(cdv, ['cdv_number', 'cdv_date', 'vendor_name',
                                               'payment_method', 'total_amount', 'status'])
            )
            flash(f'CDV "{cdv.cdv_number}" entered successfully!', 'success')
            return redirect(url_for('cash_disbursements.view', id=cdv.id))

        except CDVLineError as ce:
            db.session.rollback()
            flash(str(ce), 'error')
            return _render_form()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating CDV', exc_info=True)
            log_exception(e, severity='ERROR', module='cash_disbursements.create')
            flash('An unexpected error occurred while entering the CDV. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    if request.method == 'GET':
        form.cdv_number.data = generate_cdv_number()
        form.cdv_date.data = ph_now().date()

    return _render_form()


@cash_disbursements_bp.route('/cash-disbursements/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit(id):
    cdv = _get_cdv_or_404(id)
    if cdv.status != 'draft':
        flash('Only draft CDVs can be edited.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))

    form = CashDisbursementForm(obj=cdv)
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.code).all()
    form.vendor_id.choices = [(v.id, f'{v.code} - {v.name}') for v in vendors]
    all_accounts = _get_all_accounts_for_select()
    form.cash_account_id.choices = [
        (a['id'], f"{a['code']} — {a['name']}") for a in all_accounts if not a['is_group']
    ]

    # Serialize existing lines so the form template can restore them in edit mode
    # (the restore loop iterates `ap_lines` / `expense_lines`).
    tmpl_ap_lines = [l.to_dict() for l in cdv.ap_lines]
    tmpl_expense_lines = [l.to_dict() for l in cdv.expense_lines]

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.cdv_date.data, 'Cash Disbursement Voucher'):
            ctx = _form_context(all_accounts=all_accounts)
            return render_template('cash_disbursements/form.html', form=form, cdv=cdv,
                               ap_lines=tmpl_ap_lines, expense_lines=tmpl_expense_lines, **ctx)
        try:
            vendor = Vendor.query.get(form.vendor_id.data)
            if not vendor:
                flash('Selected vendor not found.', 'error')
                ctx = _form_context(all_accounts=all_accounts)
                return render_template('cash_disbursements/form.html', form=form, cdv=cdv,
                               ap_lines=tmpl_ap_lines, expense_lines=tmpl_expense_lines, **ctx)

            cdv.cdv_date = form.cdv_date.data
            cdv.vendor_id = vendor.id
            cdv.vendor_name = vendor.name
            cdv.vendor_tin = vendor.tin
            cdv.payment_method = form.payment_method.data
            cdv.check_number = form.check_number.data or None
            cdv.check_date = form.check_date.data or None
            cdv.check_bank = form.check_bank.data or None
            cdv.cash_account_id = form.cash_account_id.data
            cdv.notes = form.notes.data

            # Delete old line items and rebuild
            for ap in list(cdv.ap_lines):
                db.session.delete(ap)
            for exp in list(cdv.expense_lines):
                db.session.delete(exp)
            cdv.ap_lines = []
            cdv.expense_lines = []
            db.session.flush()

            _parse_line_items(cdv)
            cdv.calculate_totals()
            err = _apply_cdv_overrides(cdv)
            if err:
                return err

            # Delete old JE and recreate
            if cdv.journal_entry_id:
                from app.journal_entries.models import JournalEntry as _JE
                old_je = db.session.get(_JE, cdv.journal_entry_id)
                cdv.journal_entry_id = None
                cdv.journal_entry = None
                db.session.flush()
                if old_je:
                    db.session.delete(old_je)
                db.session.flush()

            je = _post_cdv_je(cdv, current_user.id)
            cdv.journal_entry_id = je.id
            db.session.commit()

            log_update(
                module='cash_disbursement',
                record_id=cdv.id,
                record_identifier=f'{cdv.cdv_number} - {cdv.vendor_name}',
                old_values={}, new_values={}
            )
            flash(f'CDV "{cdv.cdv_number}" updated successfully!', 'success')
            return redirect(url_for('cash_disbursements.view', id=cdv.id))

        except CDVLineError as ce:
            db.session.rollback()
            flash(str(ce), 'error')
            ctx = _form_context(all_accounts=all_accounts)
            return render_template('cash_disbursements/form.html', form=form, cdv=cdv,
                               ap_lines=tmpl_ap_lines, expense_lines=tmpl_expense_lines, **ctx)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error editing CDV', exc_info=True)
            log_exception(e, severity='ERROR', module='cash_disbursements.edit')
            flash('An unexpected error occurred while updating the CDV. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    ctx = _form_context(all_accounts=all_accounts)
    return render_template('cash_disbursements/form.html', form=form, cdv=cdv,
                           ap_lines=tmpl_ap_lines, expense_lines=tmpl_expense_lines, **ctx)


@cash_disbursements_bp.route('/cash-disbursements/<int:id>')
@login_required
def view(id):
    cdv = _get_cdv_or_404(id)
    je_entries = _build_cdv_je_preview(cdv)
    cd_print_access = AppSettings.get_setting('cd_print_access', 'posted_only')
    return render_template('cash_disbursements/detail.html',
                           cdv=cdv, je_entries=je_entries, now=ph_now(),
                           cd_print_access=cd_print_access)


def _apply_ap_payments(cdv):
    """Increment APV bill amount_paid and reduce balance on CDV post."""
    for ap_line in cdv.ap_lines:
        bill = ap_line.accounts_payable
        bill.amount_paid = Decimal(str(bill.amount_paid)) + Decimal(str(ap_line.amount_applied))
        bill.balance = Decimal(str(bill.total_amount)) - bill.amount_paid
        if bill.balance <= 0:
            bill.status = 'paid'
        elif bill.amount_paid > 0:
            bill.status = 'partially_paid'


def _reverse_ap_payments(cdv):
    """Reverse APV bill amounts on CDV cancel. Raises ValueError on inconsistency."""
    for ap_line in cdv.ap_lines:
        bill = ap_line.accounts_payable
        new_paid = Decimal(str(bill.amount_paid)) - Decimal(str(ap_line.amount_applied))
        if new_paid < 0:
            raise ValueError(
                f'Cannot cancel: reversing payment on {ap_line.ap_number} '
                f'would result in negative amount_paid.'
            )
        bill.amount_paid = new_paid
        bill.balance = Decimal(str(bill.total_amount)) - new_paid
        if bill.amount_paid <= 0:
            bill.status = 'posted'
        else:
            bill.status = 'partially_paid'


@cash_disbursements_bp.route('/cash-disbursements/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post(id):
    cdv = _get_cdv_or_404(id)
    if cdv.status != 'draft':
        flash('Only draft CDVs can be posted.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    try:
        cdv.status = 'posted'
        cdv.posted_by_id = current_user.id
        cdv.posted_at = ph_now()
        if cdv.journal_entry:
            cdv.journal_entry.status = 'posted'
            cdv.journal_entry.posted_by_id = current_user.id
            cdv.journal_entry.posted_at = ph_now()
        _apply_ap_payments(cdv)
        db.session.commit()
        log_audit(
            module='cash_disbursement', action='post',
            record_id=cdv.id,
            record_identifier=f'{cdv.cdv_number} - {cdv.vendor_name}',
            notes=f'Posted by {current_user.username}'
        )
        flash(f'CDV "{cdv.cdv_number}" posted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error posting CDV', exc_info=True)
        log_exception(e, severity='ERROR', module='cash_disbursements.post')
        flash('An unexpected error occurred while posting the CDV. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('cash_disbursements.view', id=id))


@cash_disbursements_bp.route('/cash-disbursements/<int:id>/void', methods=['POST'])
@login_required
@staff_or_above_required
def void(id):
    cdv = _get_cdv_or_404(id)
    if cdv.status != 'draft':
        flash('Only draft CDVs can be voided.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    try:
        if cdv.journal_entry_id:
            from app.journal_entries.models import JournalEntry as _JE
            je_to_delete = db.session.get(_JE, cdv.journal_entry_id)
            if je_to_delete:
                db.session.delete(je_to_delete)
            cdv.journal_entry_id = None
            cdv.journal_entry = None
        cdv.status = 'voided'
        cdv.voided_at = ph_now()
        cdv.voided_by_id = current_user.id
        cdv.void_reason = void_reason
        db.session.commit()
        log_audit(
            module='cash_disbursement', action='void',
            record_id=cdv.id,
            record_identifier=f'{cdv.cdv_number} - {cdv.vendor_name}',
            notes=f'Voided by {current_user.username}. Reason: {void_reason}'
        )
        flash(f'CDV "{cdv.cdv_number}" voided.', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error voiding CDV', exc_info=True)
        log_exception(e, severity='ERROR', module='cash_disbursements.void')
        flash('An unexpected error occurred while voiding the CDV. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('cash_disbursements.view', id=id))


@cash_disbursements_bp.route('/cash-disbursements/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    cdv = _get_cdv_or_404(id)
    if cdv.status != 'posted':
        flash('Only posted CDVs can be cancelled.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Cancellation reason must be at least 10 characters.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    try:
        _reverse_ap_payments(cdv)
        _create_cdv_reversal_je(cdv, reversal_date, current_user.id)
        cdv.status = 'cancelled'
        cdv.cancelled_at = ph_now()
        cdv.cancel_reason = cancel_reason
        db.session.commit()
        log_audit(
            module='cash_disbursement', action='cancel',
            record_id=cdv.id,
            record_identifier=f'{cdv.cdv_number} - {cdv.vendor_name}',
            notes=f'Cancelled by {current_user.username}. Reason: {cancel_reason}'
        )
        flash(f'CDV "{cdv.cdv_number}" cancelled. Reversal JE created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error cancelling CDV', exc_info=True)
        log_exception(e, severity='ERROR', module='cash_disbursements.cancel')
        flash('An unexpected error occurred while cancelling the CDV. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('cash_disbursements.view', id=id))


@cash_disbursements_bp.route('/cash-disbursements/<int:id>/print')
@login_required
def print_cdv(id):
    cdv = _get_cdv_or_404(id)
    je_entries = _build_cdv_je_preview(cdv)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('cash_disbursements/print.html',
                           cdv=cdv, je_entries=je_entries,
                           company=company, printed_at=ph_now())


def _cdv_export_data(branch_id):
    """Return (data_dicts, columns, headers) for CDV list export.

    Applies the same filters as list_cdvs (status, vendor, payment_method,
    date_from, date_to).  Returns pre-built dicts so that export_to_excel /
    export_to_csv can consume them via the dict path.
    """
    q = CashDisbursementVoucher.query.filter_by(branch_id=branch_id)

    status = request.args.get('status', '')
    vendor_id = request.args.get('vendor', '')
    payment_method = request.args.get('payment_method', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    if status and status != 'all':
        q = q.filter(CashDisbursementVoucher.status == status)
    if vendor_id and vendor_id != 'all':
        try:
            q = q.filter(CashDisbursementVoucher.vendor_id == int(vendor_id))
        except ValueError:
            pass
    if payment_method and payment_method != 'all':
        q = q.filter(CashDisbursementVoucher.payment_method == payment_method)
    if date_from:
        try:
            q = q.filter(CashDisbursementVoucher.cdv_date >= date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(CashDisbursementVoucher.cdv_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    cdvs = q.order_by(CashDisbursementVoucher.cdv_date.desc(),
                      CashDisbursementVoucher.cdv_number.desc()).all()

    columns = [
        'CDV Number', 'Date', 'Vendor', 'Payment Method',
        'Check #', 'Check Date', 'Cash/Bank Account',
        'AP Applied', 'Direct Expenses', 'Input VAT', 'WHT',
        'Net Disbursed', 'Status',
    ]
    data = []
    for cdv in cdvs:
        data.append({
            'CDV Number': cdv.cdv_number,
            'Date': cdv.cdv_date.strftime('%Y-%m-%d') if cdv.cdv_date else '',
            'Vendor': cdv.vendor_name,
            'Payment Method': (cdv.payment_method.replace('_', ' ').title()
                               if cdv.payment_method else ''),
            'Check #': cdv.check_number or '',
            'Check Date': cdv.check_date.strftime('%Y-%m-%d') if cdv.check_date else '',
            'Cash/Bank Account': (
                f'{cdv.cash_account.code} — {cdv.cash_account.name}'
                if cdv.cash_account else ''
            ),
            'AP Applied': float(cdv.total_ap_applied or 0),
            'Direct Expenses': float(cdv.total_expense or 0),
            'Input VAT': float(cdv.total_vat or 0),
            'WHT': float(cdv.total_wt or 0),
            'Net Disbursed': float(cdv.total_amount or 0),
            'Status': cdv.status.title() if cdv.status else '',
        })
    return data, columns, columns  # columns == headers for dict-based export


@cash_disbursements_bp.route('/cash-disbursements/export/excel')
@login_required
def export_excel():
    branch_id = session.get('selected_branch_id')
    data, columns, headers = _cdv_export_data(branch_id)
    return export_to_excel(
        data=data,
        columns=columns,
        headers=headers,
        filename=f'cash_disbursements_{ph_now().strftime("%Y%m%d")}.xlsx',
        title='Cash Disbursements',
    )


@cash_disbursements_bp.route('/cash-disbursements/export/csv')
@login_required
def export_csv():
    branch_id = session.get('selected_branch_id')
    data, columns, headers = _cdv_export_data(branch_id)
    return export_to_csv(
        data=data,
        columns=columns,
        headers=headers,
        filename=f'cash_disbursements_{ph_now().strftime("%Y%m%d")}.csv',
    )
