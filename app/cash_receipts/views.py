from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, abort, current_app
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy.orm import selectinload
from app import db
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine, CRVRevenueLine
from app.sales_invoices.models import SalesInvoice
from app.customers.models import Customer
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
    """Generate next CRV number: CR-YYYY-MM-NNNN, sequential per month."""
    now = ph_now()
    prefix = f'CR-{now.year}-{now.month:02d}-'
    latest = CashReceiptVoucher.query.filter(
        CashReceiptVoucher.crv_number.like(f'{prefix}%')
    ).order_by(CashReceiptVoucher.crv_number.desc()).first()
    if latest:
        try:
            last_num = int(latest.crv_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    return f'{prefix}{next_num:04d}'


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
    if Decimal(str(crv.total_vat)) <= 0:
        return []
    categories = {c.code: c for c in VATCategory.query.all()}
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
    return [(acct, amt) for acct, amt in ordered if amt != Decimal('0.00')]


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
