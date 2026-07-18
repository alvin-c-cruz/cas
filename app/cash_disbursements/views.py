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
from app.common.vat_nature import resolve_purchase_nature
from app.audit.utils import log_create, log_update, log_audit, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.cache_helpers import get_active_units, get_active_products
from app.utils.concurrency import (claim_version, conflict_message, submitted_version,
                                    fresh_number_if_collision, flush_or_suggest_fresh_number)
from app.utils.export import export_to_excel, export_to_csv
from app.utils.line_mode import validate_line_mode
from app.settings import AppSettings
from app.periods.utils import validate_transaction_date_with_flash
from app.journal_entries.utils import generate_entry_number, generate_jv_number
from app.posting.buckets import group_tax_buckets, reconcile_buckets_to_total
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
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def staff_or_above_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
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
    cdv = db.get_or_404(CashDisbursementVoucher, id)
    if cdv.branch_id != session.get('selected_branch_id'):
        abort(404)
    return cdv


def _get_gl_accounts():
    """Return the AP-Trade and WHT-Payable control accounts for display/preview
    use. Resolved via accountant-assigned settings (app.posting.control_accounts)
    -- never raises; entries are None when unassigned or misconfigured. The
    posting engine (_post_cdv_je) resolves these itself with required=True
    instead of going through this helper. Mirrors accounts_payable's
    _get_gl_accounts (feedback-cdv-crv-parity-mirror)."""
    from app.posting.control_accounts import get_control_account
    return {
        'ap': get_control_account('ap_trade', required=False),
        'wt': get_control_account('wht_payable', required=False),
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
    # Each bill's own resolved AP-Trade account -- fallback to the global default
    # mirrors the server-side resolution in _je_lines_for_display/_post_cdv_je
    # (BUG-CDCR-LIVE-PREVIEW-IGNORES-PER-LINE-ACCOUNT). The client-side live JE
    # preview needs this to bucket settlement rows per-account instead of lumping
    # every bill into one row.
    global_ap = _get_gl_accounts()['ap']
    return jsonify([{
        'id': b.id,
        'bill_number': b.ap_number,
        'vendor_invoice_number': b.vendor_invoice_number or '',
        'bill_date': b.ap_date.isoformat(),
        'balance': float(b.balance),
        'account_code': b.ap_trade_account.code if b.ap_trade_account else (global_ap.code if global_ap else None),
        'account_name': b.ap_trade_account.name if b.ap_trade_account else (global_ap.name if global_ap else None),
    } for b in bills])


def _cdv_input_vat_buckets(cdv):
    """Group expense lines' input VAT by VATCategory.input_vat_account."""
    if Decimal(str(cdv.total_vat)) == 0:
        return []
    categories = {c.code: c for c in VATCategory.query.all()}

    def _account_of(line):
        cat = categories.get(line.vat_category)
        return cat.input_vat_account if cat else None

    def _missing_account(line):
        cat = categories.get(line.vat_category)
        label = cat.code if cat else (line.vat_category or 'unknown')
        return f"VAT category '{label}' has no Input Tax account configured."

    buckets = group_tax_buckets(
        cdv.expense_lines,
        # Skip non-positive lines (simplified design -- negative lines have no VAT)
        line_skip=lambda line: Decimal(str(line.line_total)) <= Decimal('0'),
        amount_of=lambda line: line.vat_amount,
        account_of=_account_of,
        amount_predicate=lambda amt: amt != Decimal('0.00'),
        on_missing_account=_missing_account,
    )
    # Reconcile only under an explicit VAT override; largest bucket by absolute
    # value (sign-aware, so negative buckets are handled); no negative guard.
    return reconcile_buckets_to_total(
        buckets, cdv.total_vat, only_if=cdv.vat_override, largest_by='abs',
        allow_negative=True,
    )


def _cdv_wht_payable_buckets(cdv, fallback_acct):
    """Group the voucher's WHT by each expense line's ATC payable_account (fallback_acct when
    the ATC has none). Returns SIGNED amounts (positive credit, negative debit), ordered by
    account code. Mirrors _cdv_input_vat_buckets / AP's _wht_payable_buckets.

    When cdv.wt_override is set, the bucket sum is reconciled to cdv.total_wt: any diff is
    absorbed into the largest bucket, or — if there are no buckets at all (no expense line
    carries WHT) but total_wt is non-zero — placed in a single fallback_acct bucket. When NOT
    overridden this reconciliation is a no-op (cdv.total_wt already equals the summed line WHT),
    so the non-override path returns byte-identical results to the summed line WHT.

    The override WHT is never silently dropped or misstated: if there is a non-zero amount to
    place but no bucket and no fallback_acct to place it in, or if absorbing the diff would
    drive any bucket negative, this raises ValueError rather than returning an incomplete or
    negative result.

    Negative Section-B lines never carry WHT (mirrors the existing _post_cdv_je /
    _build_cdv_je_preview guard: `_parse_and_attach_expense_lines` zeroes `wt_amount`
    on negative lines at data-entry, but this is a defense-in-depth re-check here too)."""
    def _account_of(el):
        wtx = el.withholding_tax
        return wtx.payable_account if wtx and wtx.payable_account else fallback_acct

    buckets = group_tax_buckets(
        cdv.expense_lines,
        line_skip=lambda el: Decimal(str(el.line_total or 0)) <= Decimal('0.00'),
        amount_of=lambda el: el.wt_amount,
        account_of=_account_of,
        amount_predicate=lambda amt: amt != Decimal('0.00'),
        on_missing_account='skip',
    )
    # Reconcile to cdv.total_wt only under an explicit override; largest bucket
    # by absolute value; the empty+fallback branch books a pure override, and the
    # negative guard (always on for WHT) rejects an override that overshoots.
    return reconcile_buckets_to_total(
        buckets, cdv.total_wt, only_if=cdv.wt_override, largest_by='abs',
        fallback_account=fallback_acct, allow_negative=False,
        negative_error=(
            'Withholding tax override is too far below the computed WHT to allocate '
            'across payable accounts. Adjust the override or the line withholding.'),
        empty_error=(
            "Withholding tax override is non-zero but no expense line carries WHT "
            "and no Withholding Tax Payable control account was found in the COA. "
            "Adjust the override or configure the WHT Payable account."),
    )


def _post_cdv_je(cdv, user_id):
    """Create a draft or posted disbursement JE for a CDV (sign-aware for negative Section B)."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.posting.control_accounts import get_control_account

    ap_account = get_control_account('ap_trade')

    cash_account = cdv.cash_account
    if not cash_account:
        raise ValueError("Cash/Bank account not found.")

    # WHT pre-flight: guard on the amount actually being POSTED. Under wt_override that is
    # cdv.total_wt (a pure override can carry no line-level wt_amount at all, so summing the
    # lines would see 0 and miss a missing WHT account); otherwise it's the summed line WHT
    # from positive expense lines only (negative lines have no WHT).
    posted_wt = (
        Decimal(str(cdv.total_wt)) if cdv.wt_override else
        sum(
            Decimal(str(el.wt_amount or 0))
            for el in cdv.expense_lines
            if Decimal(str(el.line_total or 0)) > 0
        )
    )
    # Resolved here (required) as the per-line fallback that _cdv_wht_payable_buckets()
    # below uses when a line's ATC has no payable_account of its own. Mirrors AP's
    # _post_ap_je (feedback-cdv-crv-parity-mirror).
    wt_account = get_control_account('wht_payable') if posted_wt != Decimal('0.00') else None

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
    all_lines = []

    # AP lines: Dr AP -- each line inherits the account from the SPECIFIC bill
    # it settles (its own ap_trade_account, set when that bill posted), not
    # one shared account for the whole voucher. Falls back to the global
    # default only if the bill predates the per-transaction field.
    for ap_line in cdv.ap_lines:
        line_ap_account = ap_line.accounts_payable.ap_trade_account or ap_account
        je_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=line_ap_account.id,
            description=f'AP Payment: {ap_line.ap_number}',
            debit_amount=Decimal(str(ap_line.amount_applied)),
            credit_amount=Decimal('0.00')
        )
        db.session.add(je_line)
        all_lines.append(je_line)
        line_num += 1

    # Expense lines: positive → Dr Expense (VAT-extracted); negative → Cr Expense (bare, no VAT)
    positive_auto_vat = sum(
        Decimal(str(el.vat_amount or 0))
        for el in cdv.expense_lines
        if Decimal(str(el.line_total or 0)) > 0
    )
    override_delta = (Decimal(str(cdv.total_vat)) - positive_auto_vat
                      if cdv.vat_override else Decimal('0.00'))
    first_positive_expense = True
    for exp_line in cdv.expense_lines:
        if not exp_line.account_id:
            continue
        line_total = Decimal(str(exp_line.line_total or 0))
        if line_total < Decimal('0.00'):
            # Negative line: bare amount only — no VAT, no WHT
            je_line = JournalEntryLine(
                entry_id=je.id, line_number=line_num,
                account_id=exp_line.account_id,
                description=exp_line.description or '',
                debit_amount=Decimal('0.00'), credit_amount=abs(line_total)
            )
            db.session.add(je_line)
            all_lines.append(je_line)
            line_num += 1
        else:
            # Positive line: VAT-inclusive extraction + override absorber on first positive
            net_base = line_total - Decimal(str(exp_line.vat_amount or 0))
            if first_positive_expense:
                net_base -= override_delta
                first_positive_expense = False
            if net_base >= Decimal('0.00'):
                dr, cr = net_base, Decimal('0.00')
            else:
                dr, cr = Decimal('0.00'), abs(net_base)
            je_line = JournalEntryLine(
                entry_id=je.id, line_number=line_num,
                account_id=exp_line.account_id,
                description=exp_line.description or '',
                debit_amount=dr, credit_amount=cr
            )
            db.session.add(je_line)
            all_lines.append(je_line)
            line_num += 1

    # Input VAT buckets — sign-aware
    for vat_acct, vat_amt in _cdv_input_vat_buckets(cdv):
        if vat_amt > Decimal('0.00'):
            dr, cr = vat_amt, Decimal('0.00')
        elif vat_amt < Decimal('0.00'):
            dr, cr = Decimal('0.00'), abs(vat_amt)
        else:
            continue
        vat_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=vat_acct.id,
            description=f'Input VAT: {cdv.cdv_number}',
            debit_amount=dr, credit_amount=cr
        )
        db.session.add(vat_line)
        all_lines.append(vat_line)
        line_num += 1

    # WHT Payable — sign-aware, per ATC payable account
    for wt_acct, wt_amt in _cdv_wht_payable_buckets(cdv, wt_account):
        if wt_amt > Decimal('0.00'):
            wt_dr, wt_cr = Decimal('0.00'), wt_amt
        else:
            wt_dr, wt_cr = abs(wt_amt), Decimal('0.00')
        wt_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_acct.id,
            description=f'WHT Payable: {cdv.cdv_number}',
            debit_amount=wt_dr, credit_amount=wt_cr
        )
        db.session.add(wt_line)
        all_lines.append(wt_line)
        line_num += 1

    # Cash line — computed from net residual of all other lines
    sum_dr = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_cr = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    cash_net = sum_dr - sum_cr   # positive = cash goes out (Cr Cash); negative = cash comes in (Dr Cash)
    if cash_net >= Decimal('0.00'):
        cash_dr, cash_cr = Decimal('0.00'), cash_net
    else:
        cash_dr, cash_cr = abs(cash_net), Decimal('0.00')
    cash_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=cash_account.id,
        description=f'CD {cdv.cdv_number} — {cdv.vendor_name}',
        debit_amount=cash_dr, credit_amount=cash_cr
    )
    db.session.add(cash_line)
    all_lines.append(cash_line)

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

    entry_number = generate_jv_number(cdv.branch_id)  # reversal is a General Journal entry
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


def _debits_first(rows):
    """Presentation rule: DEBIT legs before CREDIT legs (a posted voucher stores its JE
    credit-first, so stored order would show credits above debits). Intra-group order is
    preserved. See [[crv-cdv-je-debit-order]]."""
    debits = [r for r in rows if (r['debit'] or 0) > 0]
    credits = [r for r in rows if not ((r['debit'] or 0) > 0)]
    return debits + credits


def _build_cdv_je_preview(cdv):
    """Return [{code, name, debit, credit}] for the JE section on the detail page,
    always debits-first."""
    if cdv.journal_entry:
        return _debits_first([
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in cdv.journal_entry.lines.all()
        ])
    accts = _get_gl_accounts()
    entries = []
    for ap_line in cdv.ap_lines:
        line_ap_account = ap_line.accounts_payable.ap_trade_account or accts['ap']
        if line_ap_account:
            entries.append({'code': line_ap_account.code, 'name': line_ap_account.name,
                            'debit': Decimal(str(ap_line.amount_applied)), 'credit': Decimal('0.00')})
    # Expense lines: positive → Dr Expense (VAT-extracted); negative → Cr Expense (bare, no VAT)
    positive_auto_vat = sum(
        Decimal(str(el.vat_amount or 0))
        for el in cdv.expense_lines
        if Decimal(str(el.line_total or 0)) > 0
    )
    override_delta = (Decimal(str(cdv.total_vat)) - positive_auto_vat
                      if cdv.vat_override else Decimal('0.00'))
    first_positive_expense = True
    for exp_line in cdv.expense_lines:
        if not exp_line.account_id or not exp_line.account:
            continue
        line_total = Decimal(str(exp_line.line_total or 0))
        if line_total < Decimal('0.00'):
            entries.append({'code': exp_line.account.code, 'name': exp_line.account.name,
                            'debit': Decimal('0.00'), 'credit': abs(line_total)})
        else:
            net_base = line_total - Decimal(str(exp_line.vat_amount or 0))
            if first_positive_expense:
                net_base -= override_delta
                first_positive_expense = False
            if net_base >= Decimal('0.00'):
                dr, cr = net_base, Decimal('0.00')
            else:
                dr, cr = Decimal('0.00'), abs(net_base)
            entries.append({'code': exp_line.account.code, 'name': exp_line.account.name,
                            'debit': dr, 'credit': cr})
    try:
        for vat_acct, vat_amt in _cdv_input_vat_buckets(cdv):
            if vat_amt > Decimal('0.00'):
                entries.append({'code': vat_acct.code, 'name': vat_acct.name,
                                'debit': vat_amt, 'credit': Decimal('0.00')})
            elif vat_amt < Decimal('0.00'):
                entries.append({'code': vat_acct.code, 'name': vat_acct.name,
                                'debit': Decimal('0.00'), 'credit': abs(vat_amt)})
    except ValueError:
        pass
    # WHT — per ATC payable account, sign-aware
    try:
        for wt_acct, wt_amt in _cdv_wht_payable_buckets(cdv, accts['wt']):
            if wt_amt > Decimal('0.00'):
                entries.append({'code': wt_acct.code, 'name': wt_acct.name,
                                'debit': Decimal('0.00'), 'credit': wt_amt})
            else:
                entries.append({'code': wt_acct.code, 'name': wt_acct.name,
                                'debit': abs(wt_amt), 'credit': Decimal('0.00')})
    except ValueError:
        pass
    if cdv.cash_account:
        sum_dr = sum(e['debit'] for e in entries)
        sum_cr = sum(e['credit'] for e in entries)
        cash_net = sum_dr - sum_cr
        if cash_net >= Decimal('0.00'):
            entries.append({'code': cdv.cash_account.code, 'name': cdv.cash_account.name,
                            'debit': Decimal('0.00'), 'credit': cash_net})
        else:
            entries.append({'code': cdv.cash_account.code, 'name': cdv.cash_account.name,
                            'debit': abs(cash_net), 'credit': Decimal('0.00')})
    return _debits_first(entries)


def _parse_and_attach_expense_lines(cdv, exp_lines_json):
    """Parse and attach CDVExpenseLine objects from a JSON string to *cdv*.

    Validates that every expense line has a valid, postable (leaf) account —
    an unconditional server-side guard that must NOT be weakened.  The JE builder
    silently skips None-account lines, so a crafted POST without an account would
    misattribute the line amount via the residual absorber.

    Raises CDVLineError (user-safe, flashed by the caller) on any invalid line.
    """
    try:
        exp_lines = json.loads(exp_lines_json) if exp_lines_json else []
    except (json.JSONDecodeError, TypeError):
        exp_lines = []

    def _dec(v):
        """Return Decimal(v) or None on missing/null/invalid input."""
        try:
            return Decimal(str(v)) if v not in (None, '', 'null') else None
        except (InvalidOperation, TypeError):
            return None

    def _int(v):
        """Return int(v) or None on missing/null/invalid input."""
        try:
            return int(v) if v and str(v).strip() not in ('', 'null') else None
        except (ValueError, TypeError):
            return None

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
            wt_obj = db.session.get(WithholdingTax, wt_id)
            if wt_obj:
                wt_rate = wt_obj.rate
        qty = _dec(item.get('quantity'))
        unit_price = _dec(item.get('unit_price'))
        try:
            validate_line_mode(_int(item.get('product_id')), qty, unit_price,
                               amount, line_number=idx)
        except ValueError as e:
            raise CDVLineError(str(e))

        exp_line = CDVExpenseLine(
            line_number=idx,
            description=item.get('description', ''),
            amount=amount,
            quantity=qty,
            unit_price=unit_price,
            uom_text=(item.get('uom_text') or None),
            unit_of_measure_id=_int(item.get('uom_id')),
            product_id=_int(item.get('product_id')),
            vat_category=vat_category,
            vat_nature=resolve_purchase_nature(vat_category),
            vat_rate=vat_rate,
            account_id=account_id,
            wt_id=wt_id,
            wt_rate=wt_rate,
        )
        exp_line.calculate_amounts()
        # Negative lines: no VAT, no WHT (zero out what calculate_amounts stored)
        if (exp_line.amount or Decimal('0')) < Decimal('0'):
            exp_line.vat_amount = Decimal('0.00')
            exp_line.wt_amount = Decimal('0.00')
        cdv.expense_lines.append(exp_line)


def _units_for_form():
    """Return list of active UOM dicts for form JS."""
    return [u.to_dict() for u in get_active_units()]


def _products_for_form():
    """Return list of active product dicts for form JS."""
    return [p.to_dict() for p in get_active_products()]


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
    exp_lines_json = exp_lines_data[0] if exp_lines_data and exp_lines_data[0] else '[]'
    _parse_and_attach_expense_lines(cdv, exp_lines_json)


def _form_context(all_accounts=None, selected_vendor_id=None):
    """Shared context for create/edit form rendering.

    Pass the already-built `all_accounts` list (callers need it for the cash /
    expense account selects) so the hierarchy isn't recomputed a second time.
    """
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    if all_accounts is None:
        all_accounts = _get_all_accounts_for_select()
    vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
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
    # The selected vendor's assigned WHT codes drive the direct-expense WT
    # dropdown (mirrors APV). Empty on create; the vendor's codes on edit/bounce
    # so the synchronous line-restore builds correctly-scoped selects.
    vendor_whts = []
    if selected_vendor_id:
        _v = db.session.get(Vendor, selected_vendor_id)
        if _v:
            vendor_whts = [w.to_dict() for w in _v.withholding_taxes if w.is_active]
    return dict(vendors=vendors, all_accounts=all_accounts,
                vat_categories=vat_categories,
                vendor_whts=vendor_whts,
                gl_accounts=gl_accounts,
                vendor_quick_add_form=quick_add_form,
                vendor_quick_add_whts=quick_add_whts,
                units=_units_for_form(),
                products=_products_for_form())


def _check_serial_error(cdv):
    """Friendly message if this check CDV's serial duplicates another NON-voided CDV on the
    same cash/bank account, else None. Fires only for a non-blank check_number. The DB
    partial-unique index `uq_cdv_cash_account_check_number` is the hard guard (wins the
    TOCTOU race); this is a clean flash before it fires. (A voided serial is free to reuse.)"""
    num = (cdv.check_number or '').strip()
    if cdv.payment_method != 'check' or not num:
        return None
    q = CashDisbursementVoucher.query.filter(
        CashDisbursementVoucher.cash_account_id == cdv.cash_account_id,
        db.func.trim(CashDisbursementVoucher.check_number) == num,
        CashDisbursementVoucher.status.notin_(['voided', 'cancelled']),
    )
    if cdv.id:
        q = q.filter(CashDisbursementVoucher.id != cdv.id)
    conflict = q.first()
    return (f'Check number "{num}" is already used on {conflict.cdv_number} for this '
            f'cash/bank account.') if conflict else None


@cash_disbursements_bp.route('/cash-disbursements/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    form = CashDisbursementForm()
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.code).all()
    form.vendor_id.choices = [(v.id, f'{v.code} - {v.name}') for v in vendors]
    all_accounts = _get_all_accounts_for_select()
    from app.bank_accounts.service import cash_bank_account_choices
    form.cash_account_id.choices = [(0, '-- Select Account --')] + cash_bank_account_choices(
        session.get('selected_branch_id'))

    def _render_form():
        """Render the create form. On a failed POST, carry the submitted AP/expense
        lines back so they aren't wiped."""
        is_post = request.method == 'POST'
        return render_template('cash_disbursements/form.html', form=form, cdv=None,
                               restore_ap_lines=request.form.get('ap_lines', '') if is_post else '',
                               restore_expense_lines=request.form.get('expense_lines', '') if is_post else '',
                               **_form_context(all_accounts=all_accounts,
                                               selected_vendor_id=(form.vendor_id.data if is_post else None)))

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.cdv_date.data, 'Cash Disbursement Voucher'):
            return _render_form()
        # Uniqueness check: the user-typed (or pre-filled) CD number must not
        # already be in use by any other CDV (regardless of status).
        cdv_number = (form.cdv_number.data or '').strip()
        fresh = fresh_number_if_collision(CashDisbursementVoucher, 'cdv_number',
                                           cdv_number, generate_cdv_number)
        if fresh is not None:
            form.cdv_number.data = fresh
            flash(f'CD number "{cdv_number}" is already in use. A new number '
                  f'({fresh}) has been suggested below -- review and Save again.', 'error')
            return _render_form()
        try:
            vendor = db.session.get(Vendor, form.vendor_id.data)
            if not vendor:
                flash('Selected vendor not found.', 'error')
                return _render_form()

            cdv = CashDisbursementVoucher(
                branch_id=session.get('selected_branch_id'),
                cdv_number=cdv_number,
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
            cdv.check_number = (cdv.check_number or '').strip() or None
            serial_err = _check_serial_error(cdv)
            if serial_err:
                flash(serial_err, 'error')
                return _render_form()
            _parse_line_items(cdv)
            cdv.calculate_totals()
            err = _apply_cdv_overrides(cdv)
            if err:
                return err

            db.session.add(cdv)
            # Backstop for the pre-check above: a genuinely simultaneous request can pass
            # it before either has committed, so the real collision surfaces here instead.
            # (Only re-raises for cdv_number specifically -- CD's OTHER unique constraint,
            # check_number-per-cash-account, is unrelated and must not be misdiagnosed as
            # this numbering race; see flush_or_suggest_fresh_number's docstring.)
            fresh = flush_or_suggest_fresh_number(cdv, CashDisbursementVoucher, 'cdv_number',
                                                   generate_cdv_number)
            if fresh:
                form.cdv_number.data = fresh
                flash(f'CD number "{cdv_number}" was just taken by another entry (concurrent '
                      f'submission) -- a new number ({fresh}) has been suggested below. '
                      f'Please review and Save again.', 'error')
                return _render_form()

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
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
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
    from app.bank_accounts.service import cash_bank_account_choices
    form.cash_account_id.choices = cash_bank_account_choices(session.get('selected_branch_id'))

    def _render_edit_form():
        """Render the edit form.

        On a failed POST, carry the SUBMITTED lines back -- as create()'s
        _render_form already does -- instead of re-reading the stored ones.
        Re-reading silently replaced the encoder's typed lines with the
        database's, so every bounced edit lost their work.

        The template renders edit-mode rows server-side from `ap_lines` inside
        `{% if cdv %}`, while the JS restore path keys off `restore_ap_lines`.
        Both would emit rows, so the server-side loop is starved with empty
        lists whenever a restore payload is present.
        """
        ctx = _form_context(all_accounts=all_accounts,
                            selected_vendor_id=form.vendor_id.data)
        if request.method == 'POST':
            return render_template(
                'cash_disbursements/form.html', form=form, cdv=cdv,
                ap_lines=[], expense_lines=[],
                restore_ap_lines=request.form.get('ap_lines', ''),
                restore_expense_lines=request.form.get('expense_lines', ''),
                **ctx)
        return render_template(
            'cash_disbursements/form.html', form=form, cdv=cdv,
            ap_lines=[l.to_dict() for l in cdv.ap_lines],
            expense_lines=[l.to_dict() for l in cdv.expense_lines],
            **ctx)

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.cdv_date.data, 'Cash Disbursement Voucher'):
            return _render_edit_form()
        # Uniqueness check: the edited CD number must not conflict with any OTHER
        # CDV (self is excluded via id != cdv.id).
        edit_cdv_number = (form.cdv_number.data or '').strip()
        if CashDisbursementVoucher.query.filter(
                CashDisbursementVoucher.cdv_number == edit_cdv_number,
                CashDisbursementVoucher.id != cdv.id).first():
            flash(f'CD number "{edit_cdv_number}" is already in use. '
                  'Enter a unique CD number.', 'error')
            return _render_edit_form()
        try:
            vendor = db.session.get(Vendor, form.vendor_id.data)
            if not vendor:
                flash('Selected vendor not found.', 'error')
                return _render_edit_form()

            # Lost-update guard. First write of the request: everything above is
            # read-only, everything below deletes the AP/expense lines and the
            # linked JE. The check IS the write (conditional UPDATE) -- a
            # read-then-compare races, since BEGIN is deferred until the first write.
            if not claim_version(CashDisbursementVoucher, cdv.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('cash_disbursement', cdv.id), 'error')
                return _render_edit_form()

            cdv.cdv_number = edit_cdv_number
            cdv.cdv_date = form.cdv_date.data
            cdv.vendor_id = vendor.id
            cdv.vendor_name = vendor.name
            cdv.vendor_tin = vendor.tin
            cdv.payment_method = form.payment_method.data
            cdv.check_number = (form.check_number.data or '').strip() or None
            cdv.check_date = form.check_date.data or None
            cdv.check_bank = form.check_bank.data or None
            cdv.cash_account_id = form.cash_account_id.data
            cdv.notes = form.notes.data

            serial_err = _check_serial_error(cdv)
            if serial_err:
                db.session.rollback()
                flash(serial_err, 'error')
                # Was `_render_form()`, which is nested inside create() -- calling
                # it here raised NameError (HTTP 500) on this path.
                return _render_edit_form()

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
            return _render_edit_form()
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return _render_edit_form()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error editing CDV', exc_info=True)
            log_exception(e, severity='ERROR', module='cash_disbursements.edit')
            flash('An unexpected error occurred while updating the CDV. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    return _render_edit_form()


@cash_disbursements_bp.route('/cash-disbursements/<int:id>')
@login_required
def view(id):
    cdv = _get_cdv_or_404(id)
    je_entries = _build_cdv_je_preview(cdv)
    cd_print_access = AppSettings.get_setting('cd_print_access', 'posted_only')
    cd_print_form = AppSettings.get_setting('cd_print_form', 'current')

    # "Print Check" gate (mirrors the print_check route so the button never dead-ends).
    cd_check_access = AppSettings.get_setting('cd_check_print_access', 'posted_only')
    check_printable = (
        cdv.payment_method == 'check'
        and cd_check_access != 'hidden'
        and ((cdv.status == 'posted') if cd_check_access != 'draft_and_posted'
             else (cdv.status not in ('voided', 'cancelled')))
        and bool((cdv.check_number or '').strip())
        and (cdv.total_amount or 0) > 0
    )

    return render_template('cash_disbursements/detail.html',
                           cdv=cdv, je_entries=je_entries, now=ph_now(),
                           cd_print_access=cd_print_access, cd_print_form=cd_print_form,
                           check_printable=check_printable)


def _apply_ap_payments(cdv):
    """Increment APV bill amount_paid and reduce balance on CDV post."""
    for ap_line in cdv.ap_lines:
        bill = ap_line.accounts_payable
        amount_applied = Decimal(str(ap_line.amount_applied))
        current_balance = Decimal(str(bill.balance))
        if amount_applied > current_balance:
            raise ValueError(
                f'Cannot post: payment on {ap_line.ap_number} ({amount_applied}) '
                f'exceeds its current open balance ({current_balance}).')
        bill.amount_paid = Decimal(str(bill.amount_paid)) + amount_applied
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
        if bill.status in ('paid', 'partially_paid'):
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
    if not validate_transaction_date_with_flash(cdv.cdv_date, 'Cash Disbursement'):
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
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
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
    # The reversal JE posts on reversal_date, so that period must be open.
    if not validate_transaction_date_with_flash(reversal_date, 'Reversal'):
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

    cd_print_form = AppSettings.get_setting('cd_print_form', 'current')
    # 'hidden' turns CDV printing off entirely: refuse the route, not just the button.
    if cd_print_form == 'hidden':
        flash('Cash Disbursement printing is not enabled.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))

    # BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS: the detail-page button already gates on
    # cd_print_access (posted_only/draft_and_posted) -- the route must refuse the
    # same way, or a direct GET bypasses a hidden button entirely.
    cd_print_access = AppSettings.get_setting('cd_print_access', 'posted_only')
    status_ok = (cdv.status == 'posted') if cd_print_access != 'draft_and_posted' \
        else (cdv.status not in ('voided', 'cancelled'))
    if not status_ok:
        flash('This voucher is not eligible for printing yet.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))

    je_entries = _build_cdv_je_preview(cdv)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }

    # 'preprinted' -> drag-positioned data-only layout for physical pre-printed stock;
    # else the standard self-contained printable form.
    if cd_print_form == 'preprinted':
        from app.cash_disbursements.preprinted_layout import (
            get_layout, COLUMN_LABELS, FIELD_LABELS, FONT_GROUPS, PAPER_SIZES,
            PAPER_LABELS, DATE_FORMATS, TEXT_KEYS)
        # JE face is JE-BOUND: sort the stored legs debits-first (non-VAT debits ->
        # VAT debits -> credits, by code — CDV stores credit-first), split by sign,
        # tally, and tie out. An untied face is refused at the template.
        je_lines = []
        if cdv.journal_entry:
            vat_account_ids = {c.input_vat_account_id for c in VATCategory.query.all()
                               if c.input_vat_account_id}
            lines = cdv.journal_entry.lines.all()
            debit_non_vat = sorted(
                [l for l in lines if (l.debit_amount or 0) > 0 and l.account_id not in vat_account_ids],
                key=lambda l: l.account.code)
            debit_vat = sorted(
                [l for l in lines if (l.debit_amount or 0) > 0 and l.account_id in vat_account_ids],
                key=lambda l: l.account.code)
            credits = [l for l in lines if (l.credit_amount or 0) > 0]
            je_lines = debit_non_vat + debit_vat + credits
        je_debits = [l for l in je_lines if (l.debit_amount or 0) > 0]
        je_credits = [l for l in je_lines if (l.credit_amount or 0) > 0]
        je_total_debit = sum((l.debit_amount or 0) for l in je_lines)
        je_total_credit = sum((l.credit_amount or 0) for l in je_lines)
        je_tied = abs(Decimal(je_total_debit) - Decimal(je_total_credit)) < Decimal('0.005')
        return render_template(
            'cash_disbursements/print_preprinted.html', cdv=cdv,
            je_lines=je_lines, je_debits=je_debits, je_credits=je_credits,
            je_total_debit=je_total_debit, je_total_credit=je_total_credit, je_tied=je_tied,
            company=company, printed_at=ph_now(),
            layout=get_layout(cdv.branch_id), can_edit_layout=current_user.has_full_access,
            col_labels=COLUMN_LABELS, font_groups=FONT_GROUPS,
            paper_sizes=PAPER_SIZES, paper_labels=PAPER_LABELS,
            date_formats=DATE_FORMATS, field_labels=FIELD_LABELS,
            signatory_ids=TEXT_KEYS,
            date_labels={k: date(2026, 6, 17).strftime(v) for k, v in DATE_FORMATS.items()})

    return render_template('cash_disbursements/print.html',
                           cdv=cdv, je_entries=je_entries,
                           company=company, printed_at=ph_now())


@cash_disbursements_bp.route('/cash-disbursements/print-layout', methods=['POST'])
@login_required
def save_cdv_print_layout():
    """Persist the CDV pre-printed layout JSON (full-access: admin or Chief Accountant)."""
    if not current_user.has_full_access:
        abort(403)
    from app.cash_disbursements.preprinted_layout import save_layout
    data = request.get_json(silent=True) or {}
    # Per-branch layout; the session branch equals the document's branch.
    clean = save_layout(data, current_user.username, session.get('selected_branch_id'))
    return jsonify(ok=True, layout=clean)


@cash_disbursements_bp.route('/cash-disbursements/check-layout', methods=['POST'])
@login_required
def save_cd_check_layout():
    """Persist the CDV **check** overlay layout JSON (full-access: admin or Chief Accountant).

    Keyed per cash/bank account (`?account_id=<id>`); omitting it edits the Default layout.
    """
    if not current_user.has_full_access:
        abort(403)
    from app.cash_disbursements.check_layout import save_layout
    account_id = request.args.get('account_id', type=int)   # None -> the Default layout
    data = request.get_json(silent=True) or {}
    clean = save_layout(data, current_user.username, account_id)
    return jsonify(ok=True, layout=clean)


def _build_check_values(cdv, layout):
    """Return (values, error). `amount_in_words` is the legally-operative amount
    (NIL Sec.17(b)); compute it here (never in Jinja/the renderer — it raises) and
    derive figures from the SAME total_amount so the two can never drift."""
    from decimal import Decimal, InvalidOperation
    from app.cash_disbursements.check_layout import DATE_FORMATS
    from app.common.amount_to_words import amount_to_words
    try:
        amt = Decimal(str(cdv.total_amount))
        words = amount_to_words(amt)
    except (ValueError, TypeError, InvalidOperation):
        return None, 'The disbursement amount cannot be spelled onto a check.'
    date_fmt = DATE_FORMATS[layout['dateFormat']]
    values = {
        'payee': (cdv.vendor.name if cdv.vendor else cdv.vendor_name) or '',
        'check_date': cdv.check_date.strftime(date_fmt) if cdv.check_date else '',
        'amount_figures': '{:,.2f}'.format(amt),
        'amount_in_words': words,
        'memo': cdv.notes or '',
    }
    return values, None


@cash_disbursements_bp.route('/cash-disbursements/<int:id>/print-check')
@login_required
def print_check(id):
    """The check overlay page for a check-payment CDV.

    Same mechanics as the pre-printed forms: ONE page that renders the real values at the
    layout positions, prints via the browser (@page margin:0) onto the physical check, and
    (for full-access users) doubles as the layout designer -- Edit Layout + Save right here.
    The layout is resolved by -- and Edit-Layout saves to -- the voucher's cash/bank account
    (cd_check_layout:<cash_account_id>), so each bank's stock keeps its own geometry.

    Gated: check payment only, cd_check_print_access (posted/draft/hidden), a non-blank
    serial, a positive amount, and a layout whose amount/words fields are visible. Never
    falls through to any other document. No facsimile signature is drawn.
    """
    from app.audit.utils import log_audit
    from app.cash_disbursements.check_layout import (
        get_layout, FIELD_LABELS, FONT_GROUPS, PAPER_SIZES, PAPER_LABELS, DATE_FORMATS, STAR_RUN)

    cdv = _get_cdv_or_404(id)
    fail = lambda msg: (flash(msg, 'error'),
                        redirect(url_for('cash_disbursements.view', id=id)))[1]

    if cdv.payment_method != 'check':
        return fail('This voucher is not paid by check.')
    access = AppSettings.get_setting('cd_check_print_access', 'posted_only')
    if access == 'hidden':
        return fail('Check printing is not enabled.')
    status_ok = (cdv.status == 'posted') if access != 'draft_and_posted' \
        else (cdv.status not in ('voided', 'cancelled'))
    if not status_ok:
        return fail('This voucher is not eligible for check printing.')
    if not (cdv.check_number or '').strip():
        return fail('A check number is required to print the check.')
    if (cdv.total_amount or 0) <= 0:
        return fail('Cannot print a check for a zero or negative amount.')

    layout = get_layout(cdv.cash_account_id)
    values, err = _build_check_values(cdv, layout)
    if err:
        return fail(err)
    # The legally-operative amount lines must be visible (a hidden amount/words is a
    # defective instrument). Fit is a design concern handled in the in-page designer + the
    # mandatory physical test print, not a hard gate under HTML @page.
    if layout['fields']['amount_figures'].get('hidden') or layout['fields']['amount_in_words'].get('hidden'):
        return fail('The check layout hides the amount - fix the layout before printing.')

    log_audit(module='cash_disbursements', action='print_check', record_id=cdv.id,
              record_identifier=cdv.cdv_number,
              notes=f'check {cdv.check_number} / account {cdv.cash_account_id}')
    bg = AppSettings.get_setting(f'cd_check_bg:{cdv.cash_account_id}') or \
        AppSettings.get_setting('cd_check_bg')
    date_digits = ''.join(c for c in (values['check_date'] or '') if c.isdigit())
    return render_template(
        'cash_disbursements/print_check.html',
        cdv=cdv, layout=layout, values=values, bg_image=bg, star_run=STAR_RUN,
        date_digits=date_digits,
        can_edit_layout=current_user.has_full_access, account_id=cdv.cash_account_id,
        field_labels=FIELD_LABELS, font_groups=FONT_GROUPS,
        paper_sizes=PAPER_SIZES, paper_labels=PAPER_LABELS, date_formats=DATE_FORMATS,
        date_labels={k: date(2026, 6, 17).strftime(v) for k, v in DATE_FORMATS.items()})


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
