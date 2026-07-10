"""
Purchase Bill views for managing supplier invoices and expenses.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, abort, current_app, send_file
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy.orm import selectinload
from app import db
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem, AccountsPayableAttachment
from app.accounts_payable.forms import AccountsPayableForm
from app.vendors.models import Vendor
from app.vendors.forms import VendorForm
from app.vendors.utils import populate_vat_category_choices, generate_next_vendor_code
from app.vat_categories.models import VATCategory
from app.accounts.models import Account
from app.withholding_tax.models import WithholdingTax
from app.common.vat_nature import resolve_purchase_nature
from app.audit.utils import log_create, log_update, log_delete, model_to_dict, log_audit
from app.utils import ph_now
from app.utils.concurrency import claim_version, conflict_message, submitted_version
from app.utils.export import export_to_excel, export_to_csv
from app.utils.line_mode import validate_line_mode
from app.utils.cache_helpers import get_active_units, get_active_products
from app.settings import AppSettings
from app.periods.utils import validate_transaction_date_with_flash
from app.journal_entries.utils import generate_entry_number, generate_jv_number
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
import os
import uuid
from werkzeug.utils import secure_filename

accounts_payable_bp = Blueprint('accounts_payable', __name__, template_folder='templates')


def _get_gl_accounts():
    """Return the AP and WHT GL accounts used for purchase bill journal entries.

    Input VAT accounts are no longer fixed here — each VAT category carries
    its own input_vat_account (B-014); see _input_vat_buckets().
    """
    ap_acct = Account.query.filter_by(code='20101').first()
    wt_gl_acct = Account.query.filter_by(code='20301').first()
    return {
        'ap': ap_acct,
        'wt': wt_gl_acct,
    }


def _input_vat_buckets(ap):
    """Group the bill's input VAT by each line's VAT-category account (B-014).

    Returns an ordered list of (Account, Decimal) pairs (by account code).
    The whole-bill VAT override difference is applied to the largest bucket.
    Raises ValueError if a VAT-bearing line's category has no account, or
    if the override is so far below the computed VAT that a bucket would
    go negative.
    """
    if Decimal(str(ap.vat_amount)) <= 0:
        # Override of 0 (or no VAT at all): nothing to book to input tax
        # accounts; the JE's residual absorber handles any difference.
        return []

    categories = {c.code: c for c in VATCategory.query.all()}
    buckets = {}  # account_id -> [Account, Decimal]
    for item in ap.line_items:
        vat_amt = Decimal(str(item.vat_amount or 0))
        if vat_amt <= 0:
            continue
        cat = categories.get(item.vat_category)
        acct = cat.input_vat_account if cat else None
        if acct is None:
            label = cat.code if cat else (item.vat_category or 'unknown')
            raise ValueError(
                f"VAT category '{label}' has no Input Tax account configured. "
                "Set it in VAT Categories.")
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += vat_amt

    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    total = sum((amt for _, amt in ordered), Decimal('0.00'))
    override_diff = Decimal(str(ap.vat_amount)) - total
    if override_diff != Decimal('0.00') and ordered:
        largest_acct_id = max(ordered, key=lambda b: b[1])[0].id
        ordered = [
            (acct, amt + override_diff if acct.id == largest_acct_id else amt)
            for acct, amt in ordered
        ]
    ordered = [(acct, amt) for acct, amt in ordered if amt != Decimal('0.00')]
    if any(amt < Decimal('0.00') for _, amt in ordered):
        raise ValueError(
            'VAT override is too far below the computed VAT to allocate '
            'across input tax accounts. Adjust the override or the line '
            'VAT categories.')
    return ordered


def _wht_payable_buckets(ap, fallback_acct):
    """Group the bill's WHT by each line's ATC payable_account (fallback_acct when the ATC
    has none). Ordered by account code; the bill-level WHT override difference is applied to
    the largest bucket. Total equals ap.withholding_tax_amount. Mirrors _input_vat_buckets."""
    total_wt = Decimal(str(ap.withholding_tax_amount))
    if total_wt <= 0:
        return []
    buckets = {}  # account_id -> [Account, Decimal]
    for item in ap.line_items:
        wt = Decimal(str(item.wt_amount or 0))
        if wt <= 0:
            continue
        wtx = item.withholding_tax
        acct = (wtx.payable_account if wtx and wtx.payable_account else fallback_acct)
        if acct is None:
            continue
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += wt
    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    diff = total_wt - sum((amt for _, amt in ordered), Decimal('0.00'))
    if diff != Decimal('0.00'):
        if ordered:
            largest_id = max(ordered, key=lambda b: b[1])[0].id
            ordered = [(a, amt + diff if a.id == largest_id else amt) for a, amt in ordered]
        elif fallback_acct is not None:
            # The bill carries WHT but no line contributes any (a pure bill-level
            # override). Without this branch the buckets come back empty, no WHT-payable
            # leg is booked, and _post_ap_je's residual absorber silently adds the amount
            # to the first expense line -- expense overstated, WHT payable unrecorded,
            # JE still balanced. Mirrors CDV's _cdv_wht_payable_buckets.
            ordered = [(fallback_acct, diff)]
        else:
            raise ValueError(
                "Withholding tax is non-zero but no line item carries WHT and no "
                "Withholding Tax Payable - Expanded (20301) fallback account was found "
                "in the COA. Adjust the withholding or configure the WHT Payable account.")
    if any(amt < Decimal('0.00') for _, amt in ordered):
        raise ValueError(
            'Withholding tax override is too far below the computed WHT to allocate '
            'across payable accounts. Adjust the override or the line withholding.')
    return [(a, amt) for a, amt in ordered if amt != Decimal('0.00')]


def _build_je_preview(ap):
    """Return list of {code, name, debit, credit} dicts for the JE section.

    For posted bills reads from the stored JournalEntry. For drafts,
    computes the same entries the post route would create.
    """
    if ap.journal_entry:
        return [
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in ap.journal_entry.lines.all()
        ]

    accts = _get_gl_accounts()
    entries = []

    for item in ap.line_items:
        if not item.account_id or not item.account:
            continue
        net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
        entries.append({
            'code': item.account.code if item.account else '—',
            'name': item.account.name if item.account else '—',
            'debit': net_base,
            'credit': Decimal('0.00'),
        })

    try:
        vat_buckets = _input_vat_buckets(ap)
    except ValueError as e:
        # Legacy draft with an unmapped VAT-bearing category — keep the page
        # rendering and surface the problem inline instead of crashing.
        vat_buckets = []
        vat_amount = Decimal(str(ap.vat_amount))
        if vat_amount > 0:
            entries.append({
                'code': '—',
                'name': str(e),
                'debit': vat_amount,
                'credit': Decimal('0.00'),
            })
    for vat_acct, vat_amt in vat_buckets:
        if vat_amt <= 0:
            continue
        entries.append({
            'code': vat_acct.code,
            'name': vat_acct.name,
            'debit': vat_amt,
            'credit': Decimal('0.00'),
        })

    for wt_acct, wt_amt in _wht_payable_buckets(ap, accts['wt']):
        entries.append({
            'code': wt_acct.code,
            'name': wt_acct.name,
            'debit': Decimal('0.00'),
            'credit': wt_amt,
        })

    if accts['ap']:
        entries.append({
            'code': accts['ap'].code,
            'name': accts['ap'].name,
            'debit': Decimal('0.00'),
            'credit': Decimal(str(ap.total_amount)),
        })

    return entries


def _get_all_accounts_for_select():
    """Return all active accounts with is_group and depth flags for the account picker.
    Group accounts (those with children) are shown but non-selectable per hierarchy rules.
    """
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


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can manage AP Vouchers.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def staff_or_above_required(f):
    """Tier 1 AP voucher ops — staff, accountant, and admin allowed."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


VALID_AP_STATUSES = {'draft', 'posted', 'partially_paid', 'paid', 'voided', 'cancelled'}


class APVLineError(Exception):
    """Raised when a submitted AP line fails server-side validation.

    Carries a user-facing message that is safe to flash (no internal/DB detail).
    """



def _units_for_form():
    return [u.to_dict() for u in get_active_units()]


def _products_for_form():
    return [p.to_dict() for p in get_active_products()]


def _parse_payee(raw):
    """'vendor:12' | 'employee:3' -> (payee_type, payee_id) or (None, None)."""
    try:
        kind, sid = (raw or '').split(':', 1)
        if kind in ('vendor', 'employee'):
            return kind, int(sid)
    except (ValueError, AttributeError):
        pass
    return None, None


def _resolve_payee(payee_type, payee_id):
    """Return the Vendor/Employee row for the payee, or None."""
    if not payee_id:
        return None
    if payee_type == 'employee':
        from app.employees.models import Employee
        return db.session.get(Employee, payee_id)
    if payee_type == 'vendor':
        return db.session.get(Vendor, payee_id)
    return None


def _build_validated_ap_lines():
    """Parse line_items JSON from request.form, validate each line server-side,
    and return a list of (unattached) AccountsPayableItem objects.

    The account picker disables group accounts in the UI, but the POST body is
    the real trust boundary, so every line is re-validated here:
      * account_id must be an active, postable (leaf) account;
      * amount must be > 0.
    Raises APVLineError (user-facing message) on any invalid line.
    """
    line_items_data = request.form.getlist('line_items')
    if not line_items_data or not line_items_data[0]:
        raise APVLineError('Add at least one line item before saving the AP Voucher.')
    line_items = json.loads(line_items_data[0])
    if not line_items:
        raise APVLineError('Add at least one line item before saving the AP Voucher.')
    leaf_account_ids = {a['id'] for a in _get_all_accounts_for_select() if not a['is_group']}

    def _dec(v):
        try:
            return Decimal(str(v)) if v not in (None, '', 'null') else None
        except (InvalidOperation, TypeError):
            return None

    def _int_safe(v):
        try:
            return int(v) if v and str(v).strip() not in ('', 'null') else None
        except (ValueError, TypeError):
            return None

    built = []
    for idx, item_data in enumerate(line_items, start=1):
        try:
            amount = Decimal(str(item_data.get('amount', 0)))
        except (ValueError, TypeError, InvalidOperation):
            raise APVLineError('A line amount is invalid.')
        if amount <= 0:
            raise APVLineError('Each line amount must be greater than zero.')
        account_id = int(item_data.get('account_id')) if item_data.get('account_id') else None
        if account_id not in leaf_account_ids:
            raise APVLineError('Each line must use a valid, postable account.')

        vat_rate = Decimal('0.00')
        vat_category = item_data.get('vat_category')
        if vat_category:
            vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
            if vat_cat:
                vat_rate = Decimal(str(vat_cat.rate))

        wt_id = int(item_data['wt_id']) if item_data.get('wt_id') else None
        wt_rate = None
        if wt_id:
            wt_obj = db.session.get(WithholdingTax, wt_id)
            if wt_obj:
                wt_rate = wt_obj.rate

        qty = _dec(item_data.get('quantity'))
        unit_price = _dec(item_data.get('unit_price'))
        try:
            validate_line_mode(_int_safe(item_data.get('product_id')), qty, unit_price,
                               amount, line_number=idx)
        except ValueError as e:
            raise APVLineError(str(e))

        line_item = AccountsPayableItem(
            line_number=idx,
            description=item_data.get('description', ''),
            amount=amount,
            quantity=qty,
            unit_price=unit_price,
            uom_text=(item_data.get('uom_text') or None),
            unit_of_measure_id=_int_safe(item_data.get('uom_id')),
            product_id=_int_safe(item_data.get('product_id')),
            vat_category=vat_category,
            vat_nature=resolve_purchase_nature(vat_category),
            vat_rate=vat_rate,
            account_id=account_id,
            wt_id=wt_id,
            wt_rate=wt_rate,
        )
        line_item.calculate_amounts()
        built.append(line_item)
    return built


@accounts_payable_bp.before_request
def require_branch_selection():
    if current_user.is_authenticated and not session.get('selected_branch_id'):
        flash('Please select a branch to continue.', 'warning')
        return redirect(url_for('users.select_branch'))


def _get_ap_or_404(id):
    ap = db.get_or_404(AccountsPayable, id)
    if ap.branch_id != session.get('selected_branch_id'):
        abort(404)
    return ap


def _ap_upload_dir(ap_id):
    """Return (and create if needed) the upload directory for a bill's attachments."""
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'accounts_payable', str(ap_id))
    os.makedirs(path, exist_ok=True)
    return path


# Server-side allowlist: extension → canonical MIME type.
# SVG is intentionally excluded — it executes JS when served inline.
_ATTACHMENT_ALLOWED = {
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif':  'image/gif',
    '.webp': 'image/webp',
    '.pdf':  'application/pdf',
    '.doc':  'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls':  'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.csv':  'text/csv',
    '.txt':  'text/plain',
}


def _save_ap_attachment(ap, file_storage, user):
    """Validate and persist one uploaded file as an AccountsPayableAttachment.

    Saves to _ap_upload_dir(ap.id), creates the DB row, writes an audit entry,
    and commits this attachment atomically (mirrors edit-mode upload). Returns
    (True, None) on success or (False, message) on a disallowed type / invalid
    name / error — after rolling back and removing any written file. Never
    raises for those cases, so a bad file can be skipped by the caller.
    """
    original_name = secure_filename(file_storage.filename or '')
    if not original_name:
        return False, 'Invalid filename.'

    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    mime_type = _ATTACHMENT_ALLOWED.get(ext)
    if mime_type is None:
        allowed = ', '.join(sorted(_ATTACHMENT_ALLOWED))
        return False, f'File type "{ext or "unknown"}" is not allowed. Accepted: {allowed}'

    stored_name = uuid.uuid4().hex + ext
    file_path = os.path.join(_ap_upload_dir(ap.id), stored_name)
    try:
        file_storage.save(file_path)
        file_size = os.path.getsize(file_path)

        attachment = AccountsPayableAttachment(
            ap_id=ap.id,
            original_filename=original_name,
            stored_filename=stored_name,
            mime_type=mime_type,
            file_size=file_size,
            uploaded_by_id=user.id,
        )
        db.session.add(attachment)
        db.session.commit()

        log_create(
            module='accounts_payable_attachment',
            record_id=attachment.id,
            record_identifier=f'{ap.ap_number} / {original_name}',
            new_values={
                'ap_id': ap.id,
                'original_filename': original_name,
                'stored_filename': stored_name,
                'mime_type': mime_type,
                'file_size': file_size,
            },
        )
        return True, None
    except Exception:
        db.session.rollback()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        current_app.logger.error('Error saving AP attachment', exc_info=True)
        return False, 'An unexpected error occurred while saving the file.'


_EXPORT_COLUMNS = [
    'ap_number', 'ap_date', 'due_date', 'vendor_name', 'vendor_tin',
    'vendor_invoice_number', 'subtotal', 'vat_amount', 'withholding_tax_amount',
    'total_amount', 'amount_paid', 'balance', 'status',
]

_EXPORT_HEADERS = [
    'Bill #', 'Bill Date', 'Due Date', 'Vendor', 'TIN', 'Vendor Invoice #',
    'Subtotal', 'VAT', 'Withholding Tax', 'Total', 'Paid', 'Balance', 'Status',
]


def _apply_overrides(ap):
    """Apply VAT/WT manual overrides from request.form to bill.

    Mutates bill in place. Returns a redirect Response on validation error,
    or None on success. Caller must check the return value.
    """
    import decimal as _decimal
    vat_override = request.form.get('vat_override') == '1'
    wt_override = request.form.get('wt_override') == '1'
    ap.vat_override = vat_override
    ap.wt_override = wt_override
    if vat_override:
        try:
            vat_val = Decimal(request.form.get('vat_override_value', '0') or '0')
            if vat_val < 0 or vat_val > ap.subtotal:
                raise ValueError('out of range')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid VAT override value.', 'danger')
            return redirect(url_for('accounts_payable.list_ap'))
        ap.vat_amount = vat_val
    if wt_override:
        try:
            wt_val = Decimal(request.form.get('wt_override_value', '0') or '0')
            if wt_val < 0 or wt_val > ap.subtotal:
                raise ValueError('out of range')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid withholding tax override value.', 'danger')
            return redirect(url_for('accounts_payable.list_ap'))
        ap.withholding_tax_amount = wt_val
    ap.total_amount = ap.subtotal - ap.withholding_tax_amount
    ap.balance = ap.total_amount - ap.amount_paid
    return None


def _filtered_ap_query(include_ids=False):
    """Build a branch-scoped AccountsPayable query from request filter args.

    Args read: status, vendor, q, date_from, date_to — and ids when
    include_ids=True (exports only); a valid ids list overrides all
    other filters but stays branch-scoped. Invalid values are ignored.
    """
    current_branch_id = session.get('selected_branch_id')
    query = AccountsPayable.query.filter_by(branch_id=current_branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(AccountsPayable.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_AP_STATUSES:
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
        query = query.filter(db.or_(AccountsPayable.ap_number.ilike(like),
                                    AccountsPayable.vendor_name.ilike(like)))

    year = ph_now().year
    date_from = request.args.get('date_from', f'{year}-01-01')
    if date_from:
        try:
            query = query.filter(AccountsPayable.ap_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', f'{year}-12-31')
    if date_to:
        try:
            query = query.filter(AccountsPayable.ap_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@accounts_payable_bp.route('/accounts-payable')
@login_required
def list_ap():
    """List purchase bills with summary cards, filters, search, pagination."""
    from app.accounts_payable.utils import compute_ap_summary

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = (_filtered_ap_query()
             .order_by(AccountsPayable.ap_date.desc()))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    summary = compute_ap_summary(session.get('selected_branch_id'))
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('accounts_payable/list.html',
                           ap_list=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           today=ph_now().date(),
                           status_filter=request.args.get('status', 'all'),
                           vendor_filter=request.args.get('vendor', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', f'{ph_now().year}-01-01'),
                           date_to=request.args.get('date_to', f'{ph_now().year}-12-31'))


@accounts_payable_bp.route('/accounts-payable/export/excel')
@login_required
def export_excel():
    ap_list = _filtered_ap_query(include_ids=True).options(
        selectinload(AccountsPayable.line_items)
    ).order_by(AccountsPayable.ap_date.desc()).all()
    log_audit('accounts_payable','export_excel', None, f'{len(ap_list)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(
        data=ap_list,
        columns=_EXPORT_COLUMNS,
        headers=_EXPORT_HEADERS,
        filename=f'accounts_payable_{timestamp}.xlsx',
        title='Accounts Payable Report',
    )


@accounts_payable_bp.route('/accounts-payable/export/csv')
@login_required
def export_csv_route():
    ap_list = _filtered_ap_query(include_ids=True).options(
        selectinload(AccountsPayable.line_items)
    ).order_by(AccountsPayable.ap_date.desc()).all()
    log_audit('accounts_payable','export_csv', None, f'{len(ap_list)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(
        data=ap_list,
        columns=_EXPORT_COLUMNS,
        headers=_EXPORT_HEADERS,
        filename=f'accounts_payable_{timestamp}.csv',
    )


@accounts_payable_bp.route('/accounts-payable/print')
@login_required
def print_list():
    from app.settings import AppSettings
    ap_list = (_filtered_ap_query(include_ids=True)
               .order_by(AccountsPayable.ap_date.desc()).all())
    company_name = AppSettings.get_setting('company_name') or ''
    return render_template('accounts_payable/list_print.html',
                           ap_list=ap_list,
                           company_name=company_name,
                           today=ph_now().date(),
                           printed_at=ph_now(),
                           status_filter=request.args.get('status', 'all'),
                           date_from=request.args.get('date_from', f'{ph_now().year}-01-01'),
                           date_to=request.args.get('date_to', f'{ph_now().year}-12-31'))


@accounts_payable_bp.route('/accounts-payable/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    """Create new purchase bill."""
    form = AccountsPayableForm()

    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.code).all()
    form.vendor_id.choices = [(v.id, f'{v.code} - {v.name}') for v in vendors]

    def _render_form(restore_lines=''):
        """Render the create form with full line-item context. `restore_lines`
        carries the submitted line_items JSON back so a failed POST keeps the
        typed lines instead of wiping them."""
        if request.method == 'POST' and any(
                f and f.filename for f in request.files.getlist('attachments')):
            flash('Your attached files were cleared — please re-attach before saving.', 'warning')
        vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
        all_accounts = _get_all_accounts_for_select()
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
        from app.employees.models import Employee
        employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_no).all()
        current_payee = request.form.get('payee', '') if request.method == 'POST' else ''
        return render_template('accounts_payable/form.html',
                               form=form, ap=None, restore_lines=restore_lines,
                               vat_categories=vat_categories, all_accounts=all_accounts,
                               gl_accounts=gl_accounts,
                               units=_units_for_form(),
                               products=_products_for_form(),
                               vendors=vendors, employees=employees, current_payee=current_payee,
                               vendor_quick_add_form=quick_add_form,
                               vendor_quick_add_whts=quick_add_whts)

    if form.validate_on_submit():
        # Validate that the bill date is not in a closed period
        if not validate_transaction_date_with_flash(form.ap_date.data, 'AP Voucher'):
            return _render_form(request.form.get('line_items', ''))

        try:
            # Resolve the payee: prefer the combined `payee` value (vendor:<id> /
            # employee:<id>); fall back to a bare vendor_id (legacy callers/tests).
            payee_type, payee_id = _parse_payee(request.form.get('payee'))
            if payee_type is None and form.vendor_id.data:
                payee_type, payee_id = 'vendor', form.vendor_id.data
            payee = _resolve_payee(payee_type, payee_id)
            if payee is None:
                flash('Selected payee not found.', 'error')
                return _render_form(request.form.get('line_items', ''))
            is_vendor = payee_type == 'vendor'

            # B-09: block duplicate vendor invoice number per vendor (voided/cancelled
            # excluded). Employees have no vendor-invoice concept, so skip for them.
            inv_num = form.vendor_invoice_number.data
            if is_vendor and inv_num:
                dup = AccountsPayable.query.filter(
                    AccountsPayable.vendor_id == payee.id,
                    AccountsPayable.vendor_invoice_number == inv_num,
                    AccountsPayable.status.notin_(['voided', 'cancelled'])
                ).first()
                if dup:
                    flash(f"Vendor invoice number '{inv_num}' already exists for this vendor.", 'error')
                    return _render_form(request.form.get('line_items', ''))

            # User-typed AP number (mirrors SI invoice_number); must be unique.
            ap_num = (form.ap_number.data or '').strip()
            if AccountsPayable.query.filter(AccountsPayable.ap_number == ap_num).first():
                flash(f'AP number "{ap_num}" is already in use. Enter a unique AP number.', 'error')
                return _render_form(request.form.get('line_items', ''))

            ap = AccountsPayable(
                branch_id=session.get('selected_branch_id'),
                ap_number=ap_num,
                ap_date=form.ap_date.data,
                due_date=form.due_date.data,
                payee_type=payee_type,
                payee_id=payee_id,
                vendor_id=(payee.id if is_vendor else None),
                vendor_name=(payee.name if is_vendor else payee.full_name),
                vendor_tin=payee.tin,
                vendor_address=payee.address,
                vendor_invoice_number=form.vendor_invoice_number.data,
                vendor_invoice_date=form.vendor_invoice_date.data,
                payment_terms=form.payment_terms.data,
                withholding_tax_rate=Decimal('0.00'),
                reference=form.reference.data,
                notes=form.notes.data,
                status='draft',
                amount_paid=Decimal('0.00'),
                balance=Decimal('0.00'),
                created_by_id=current_user.id
            )

            for line_item in _build_validated_ap_lines():
                ap.line_items.append(line_item)

            ap.calculate_totals()

            err = _apply_overrides(ap)
            if err:
                return err

            db.session.add(ap)
            db.session.flush()  # need ap.id before creating JE

            je = _post_ap_je(ap, current_user.id)
            ap.journal_entry_id = je.id
            db.session.commit()

            log_create(
                module='accounts_payable',
                record_id=ap.id,
                record_identifier=f'{ap.ap_number} - {ap.vendor_name}',
                new_values=model_to_dict(ap, ['ap_number', 'ap_date', 'due_date', 'vendor_name', 'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])
            )

            # Persist files queued on the create form (held in the browser until
            # Save). The APV is already committed, so ap.id is stable; each file
            # commits atomically. Option (a): a bad file is skipped with a
            # warning and never blocks the voucher or the other files.
            skipped = []
            for f in request.files.getlist('attachments'):
                if not f or not f.filename:
                    continue
                ok, err = _save_ap_attachment(ap, f, current_user)
                if not ok:
                    skipped.append(f.filename)
            if skipped:
                flash('Some files were not attached and were skipped: '
                      + ', '.join(skipped), 'warning')

            flash(f'AP Voucher "{ap.ap_number}" entered successfully!', 'success')
            return redirect(url_for('accounts_payable.view', id=ap.id))

        except APVLineError as le:
            db.session.rollback()
            flash(str(le), 'error')
        except ValueError as e:
            # Deliberate, user-facing validation raised during JE assembly
            # (e.g. _input_vat_buckets: unmapped Input Tax account, override
            # too far below computed VAT). These messages are curated and safe
            # to surface — mirror the cancel() handler.
            db.session.rollback()
            flash(str(e), 'error')
        except Exception as e:
            from app.errors.utils import log_exception
            # Roll back BEFORE logging — log_exception commits the session,
            # which would otherwise persist the half-saved bill.
            db.session.rollback()
            current_app.logger.error(f"Error creating purchase bill", exc_info=True)
            log_exception(e, severity='ERROR', module='accounts_payable.create')
            flash('An unexpected error occurred while entering the AP Voucher. Please '
                  'try again; if it persists, contact your administrator.', 'error')

    if request.method == 'GET':
        form.ap_number.data = generate_ap_number()
        form.ap_date.data = ph_now().date()
        form.due_date.data = ph_now().date() + timedelta(days=30)

    # On a failed POST, carry the submitted line items back so they aren't lost.
    restore_lines = request.form.get('line_items', '') if request.method == 'POST' else ''
    return _render_form(restore_lines)


def _cdv_settlements(ap):
    """Posted Cash Disbursement Vouchers that make up this bill's Amount Paid.

    Returns the CDV AP-lines (each with its parent CDV via the ``cdv`` backref)
    that applied against this bill, oldest first. Only posted CDVs count toward
    ``amount_paid``; draft/voided are excluded.
    """
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
    return (
        CDVApLine.query
        .join(CashDisbursementVoucher, CDVApLine.cdv_id == CashDisbursementVoucher.id)
        .filter(CDVApLine.ap_id == ap.id,
                CashDisbursementVoucher.status == 'posted')
        .order_by(CashDisbursementVoucher.cdv_date, CashDisbursementVoucher.cdv_number)
        .all()
    )


@accounts_payable_bp.route('/accounts-payable/<int:id>')
@login_required
def view(id):
    """View purchase bill details."""
    ap = _get_ap_or_404(id)
    je_entries = _build_je_preview(ap)
    apv_print_access = AppSettings.get_setting('apv_print_access', 'posted_only')
    payments = _cdv_settlements(ap)
    return render_template('accounts_payable/detail.html', ap=ap,
                           je_entries=je_entries,
                           apv_print_access=apv_print_access,
                           payments=payments)


@accounts_payable_bp.route('/accounts-payable/<int:id>/print')
@login_required
def print_ap(id):
    """Standalone print preview for an APV."""
    ap = _get_ap_or_404(id)

    ap_print_form = AppSettings.get_setting('ap_print_form', 'current')
    # 'hidden' turns APV printing off entirely: refuse the route, not just the button.
    if ap_print_form == 'hidden':
        flash('APV printing is not enabled.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    # Sort JE lines: non-VAT debits → VAT debits → credits, each by account code
    je_lines = []
    if ap.journal_entry:
        vat_account_ids = {
            c.input_vat_account_id
            for c in VATCategory.query.all()
            if c.input_vat_account_id
        }
        lines = ap.journal_entry.lines.all()
        debit_non_vat = sorted(
            [line for line in lines if (line.debit_amount or 0) > 0 and line.account_id not in vat_account_ids],
            key=lambda line: line.account.code
        )
        debit_vat = sorted(
            [line for line in lines if (line.debit_amount or 0) > 0 and line.account_id in vat_account_ids],
            key=lambda line: line.account.code
        )
        credits = [line for line in lines if (line.credit_amount or 0) > 0]
        je_lines = debit_non_vat + debit_vat + credits

    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }

    # 'preprinted' -> drag-positioned data-only layout for physical pre-printed
    # stock; else the standard self-contained printable form.
    if ap_print_form == 'preprinted':
        from app.accounts_payable.preprinted_layout import (
            get_layout, COLUMN_LABELS, FIELD_LABELS, FONT_GROUPS, PAPER_SIZES,
            PAPER_LABELS, DATE_FORMATS, TEXT_KEYS)
        # JE face is JE-BOUND: split the already-debits-first legs by sign, tally, and
        # tie out. An untied face is refused at the template (never printed).
        je_debits = [l for l in je_lines if (l.debit_amount or 0) > 0]
        je_credits = [l for l in je_lines if (l.credit_amount or 0) > 0]
        je_total_debit = sum((l.debit_amount or 0) for l in je_lines)
        je_total_credit = sum((l.credit_amount or 0) for l in je_lines)
        je_tied = abs(Decimal(je_total_debit) - Decimal(je_total_credit)) < Decimal('0.005')
        return render_template(
            'accounts_payable/print_preprinted.html', ap=ap,
            je_lines=je_lines, je_debits=je_debits, je_credits=je_credits,
            je_total_debit=je_total_debit, je_total_credit=je_total_credit, je_tied=je_tied,
            company=company, printed_at=ph_now(),
            layout=get_layout(ap.branch_id), can_edit_layout=current_user.has_full_access,
            col_labels=COLUMN_LABELS, font_groups=FONT_GROUPS,
            paper_sizes=PAPER_SIZES, paper_labels=PAPER_LABELS,
            date_formats=DATE_FORMATS, field_labels=FIELD_LABELS,
            signatory_ids=TEXT_KEYS,
            date_labels={k: date(2026, 6, 17).strftime(v) for k, v in DATE_FORMATS.items()})

    return render_template(
        'accounts_payable/print.html',
        ap=ap,
        je_lines=je_lines,
        company=company,
        printed_at=ph_now(),
    )


@accounts_payable_bp.route('/accounts-payable/print-layout', methods=['POST'])
@login_required
def save_apv_print_layout():
    """Persist the APV pre-printed layout JSON (full-access: admin or Chief Accountant)."""
    if not current_user.has_full_access:
        abort(403)
    from app.accounts_payable.preprinted_layout import save_layout
    data = request.get_json(silent=True) or {}
    # Per-branch layout; the session branch equals the document's branch (see
    # _get_ap_or_404 / print page gating).
    clean = save_layout(data, current_user.username, session.get('selected_branch_id'))
    return jsonify(ok=True, layout=clean)


@accounts_payable_bp.route('/accounts-payable/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit(id):
    """Edit purchase bill (only drafts can be edited)."""
    ap = _get_ap_or_404(id)

    if ap.status != 'draft':
        flash('Only draft APVs can be edited.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    form = AccountsPayableForm(obj=ap)

    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.code).all()
    form.vendor_id.choices = [(v.id, f'{v.code} - {v.name}') for v in vendors]

    def _render_edit_form(restore_lines=''):
        """Render the edit form with the complete context required by form.html.

        Used by early-return error paths (closed period, vendor not found) so
        they don't trigger a TemplateUndefined / 500 by omitting variables that
        the template unconditionally accesses (vat_categories, all_accounts,
        gl_accounts, line_items).  Mirrors the GET/normal-path context below.
        """
        vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
        all_accounts = _get_all_accounts_for_select()
        _accts = _get_gl_accounts()
        gl_accounts = {
            'ap': {'code': _accts['ap'].code, 'name': _accts['ap'].name} if _accts['ap'] else None,
            'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
        }
        line_items = [item.to_dict() for item in ap.line_items]
        quick_add_form = VendorForm()
        populate_vat_category_choices(quick_add_form)
        quick_add_form.code.data = generate_next_vendor_code()
        quick_add_form.is_active.data = '1'
        quick_add_form.payment_terms.data = 'Net 30'
        quick_add_whts = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()
        from app.employees.models import Employee
        employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_no).all()
        if request.method == 'POST':
            current_payee = request.form.get('payee', '')
        else:
            current_payee = f'{ap.payee_type}:{ap.payee_id}'
        return render_template('accounts_payable/form.html',
                               form=form, ap=ap, restore_lines=restore_lines,
                               vat_categories=vat_categories, all_accounts=all_accounts,
                               line_items=line_items, gl_accounts=gl_accounts,
                               units=_units_for_form(), products=_products_for_form(),
                               vendors=vendors, employees=employees, current_payee=current_payee,
                               vendor_quick_add_form=quick_add_form,
                               vendor_quick_add_whts=quick_add_whts)

    if form.validate_on_submit():
        # Validate that the bill date is not in a closed period
        if not validate_transaction_date_with_flash(form.ap_date.data, 'AP Voucher'):
            return _render_edit_form(request.form.get('line_items', ''))

        try:
            old_values = model_to_dict(ap, ['ap_number', 'ap_date', 'due_date', 'vendor_name', 'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])

            # Resolve payee (combined value, or legacy bare vendor_id).
            payee_type, payee_id = _parse_payee(request.form.get('payee'))
            if payee_type is None and form.vendor_id.data:
                payee_type, payee_id = 'vendor', form.vendor_id.data
            payee = _resolve_payee(payee_type, payee_id)
            if payee is None:
                flash('Selected payee not found.', 'error')
                return _render_edit_form(request.form.get('line_items', ''))
            is_vendor = payee_type == 'vendor'

            # B-09: block duplicate vendor invoice number per vendor (exclude self;
            # voided/cancelled excluded). Skip for employee payees.
            inv_num = form.vendor_invoice_number.data
            if is_vendor and inv_num:
                dup = AccountsPayable.query.filter(
                    AccountsPayable.vendor_id == payee.id,
                    AccountsPayable.vendor_invoice_number == inv_num,
                    AccountsPayable.status.notin_(['voided', 'cancelled']),
                    AccountsPayable.id != ap.id
                ).first()
                if dup:
                    flash(f"Vendor invoice number '{inv_num}' already exists for this vendor.", 'error')
                    return _render_edit_form(request.form.get('line_items', ''))

            # User-typed AP number, editable while the (draft) form is editable; unique.
            ap_num = (form.ap_number.data or '').strip()
            if AccountsPayable.query.filter(AccountsPayable.ap_number == ap_num,
                                            AccountsPayable.id != ap.id).first():
                flash(f'AP number "{ap_num}" is already in use. Enter a unique AP number.', 'error')
                return _render_edit_form(request.form.get('line_items', ''))

            # Lost-update guard. This is the FIRST write of the request: everything
            # above is read-only, and everything below deletes the line items and
            # the linked JE. A losing racer must never reach that teardown.
            # The check IS the write (conditional UPDATE) -- a read-then-compare
            # would race, because BEGIN is deferred until the first write.
            if not claim_version(AccountsPayable, ap.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('accounts_payable', ap.id), 'error')
                return _render_edit_form(request.form.get('line_items', ''))

            ap.ap_number = ap_num
            ap.ap_date = form.ap_date.data
            ap.due_date = form.due_date.data
            ap.payee_type = payee_type
            ap.payee_id = payee_id
            ap.vendor_id = (payee.id if is_vendor else None)
            ap.vendor_name = (payee.name if is_vendor else payee.full_name)
            ap.vendor_tin = payee.tin
            ap.vendor_address = payee.address
            ap.vendor_invoice_number = form.vendor_invoice_number.data
            ap.vendor_invoice_date = form.vendor_invoice_date.data
            ap.payment_terms = form.payment_terms.data
            ap.withholding_tax_rate = Decimal('0.00')
            ap.reference = form.reference.data
            ap.notes = form.notes.data

            # Build + validate the new lines BEFORE deleting the old ones, so an
            # invalid submission rejects without destroying the existing lines.
            new_lines = _build_validated_ap_lines()
            db.session.execute(db.delete(AccountsPayableItem).where(AccountsPayableItem.ap_id == ap.id))
            for line_item in new_lines:
                line_item.ap_id = ap.id
                db.session.add(line_item)

            # flush so new rows are in DB, then expire the collection so that
            # calculate_totals() and _post_ap_je() lazy-load fresh rows instead
            # of the stale pre-delete ORM cache (bulk deletes do not evict it).
            db.session.flush()
            db.session.expire(ap, ['line_items'])

            ap.calculate_totals()

            err = _apply_overrides(ap)
            if err:
                return err

            # Delete old JE and create a fresh one
            if ap.journal_entry_id:
                from app.journal_entries.models import JournalEntry as _JE
                old_je_id_to_delete = ap.journal_entry_id
                ap.journal_entry_id = None
                ap.journal_entry = None
                db.session.flush()  # commit FK null before deleting the JE row
                old_je = db.session.get(_JE, old_je_id_to_delete)
                if old_je:
                    db.session.delete(old_je)

            db.session.flush()

            je = _post_ap_je(ap, current_user.id)
            ap.journal_entry_id = je.id
            db.session.commit()

            new_values = model_to_dict(ap, ['ap_number', 'ap_date', 'due_date', 'vendor_name', 'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])
            log_update(
                module='accounts_payable',
                record_id=ap.id,
                record_identifier=f'{ap.ap_number} - {ap.vendor_name}',
                old_values=old_values,
                new_values=new_values
            )

            flash(f'AP Voucher "{ap.ap_number}" saved successfully!', 'success')
            return redirect(url_for('accounts_payable.view', id=ap.id))

        except APVLineError as le:
            db.session.rollback()
            flash(str(le), 'error')
        except ValueError as e:
            # Deliberate, user-facing validation raised during JE assembly
            # (e.g. _input_vat_buckets). Curated messages — safe to surface.
            db.session.rollback()
            flash(str(e), 'error')
        except Exception as e:
            from app.errors.utils import log_exception
            # Roll back BEFORE logging — log_exception commits the session,
            # which would otherwise persist the half-saved changes.
            db.session.rollback()
            current_app.logger.error(f"Error updating purchase bill", exc_info=True)
            log_exception(e, severity='ERROR', module='accounts_payable.update')
            flash('An unexpected error occurred while saving the AP Voucher. Please '
                  'try again; if it persists, contact your administrator.', 'error')

    if request.method == 'GET':
        form.vendor_id.data = ap.vendor_id

    restore_lines = request.form.get('line_items', '') if request.method == 'POST' else ''
    return _render_edit_form(restore_lines)


@accounts_payable_bp.route('/accounts-payable/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post(id):
    """Post purchase bill (makes it final)."""
    ap = _get_ap_or_404(id)

    if ap.status != 'draft':
        flash('Only draft APVs can be posted.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    # Re-validate the period at post: a draft dated before a close could otherwise be
    # posted after, landing posted GL into a closed period. SI/CDV/CRV all re-check here.
    if not validate_transaction_date_with_flash(ap.ap_date, 'AP Voucher'):
        return redirect(url_for('accounts_payable.view', id=id))

    needs_invoice = ap.vat_amount > 0 or ap.withholding_tax_amount > 0
    if needs_invoice:
        missing = []
        if not ap.vendor_invoice_number:
            missing.append('Vendor Invoice #')
        if not ap.vendor_invoice_date:
            missing.append('Vendor Invoice Date')
        if missing:
            verb = 'are' if len(missing) > 1 else 'is'
            flash(f'Cannot post: {" and ".join(missing)} {verb} required when VAT or withholding tax applies.', 'error')
            return redirect(url_for('accounts_payable.view', id=id))

    try:
        ap.status = 'posted'
        ap.posted_by_id = current_user.id
        ap.posted_at = ph_now()

        # Promote the bill's draft JE so the amounts enter the books now
        if ap.journal_entry:
            ap.journal_entry.status = 'posted'
            ap.journal_entry.posted_by_id = current_user.id
            ap.journal_entry.posted_at = ph_now()
        db.session.commit()

        log_audit(
            module='accounts_payable',
            action='post',
            record_id=ap.id,
            record_identifier=f'{ap.ap_number} - {ap.vendor_name}',
            notes=f'Bill posted by {current_user.username}'
        )

        flash(f'AP Voucher "{ap.ap_number}" posted successfully!', 'success')
    except Exception as e:
        from app.errors.utils import log_exception
        # Roll back BEFORE logging — log_exception commits the session,
        # which would otherwise persist the half-applied status change.
        db.session.rollback()
        current_app.logger.error(f"Error posting purchase bill", exc_info=True)
        log_exception(e, severity='ERROR', module='accounts_payable.post')
        flash('An unexpected error occurred while posting the AP Voucher. Please '
              'try again; if it persists, contact your administrator.', 'error')

    return redirect(url_for('accounts_payable.view', id=id))


@accounts_payable_bp.route('/accounts-payable/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    """Cancel a posted purchase bill and create a reversal journal entry."""
    from app.errors.utils import log_exception
    ap = _get_ap_or_404(id)

    if ap.status != 'posted':
        flash('Only posted APVs can be cancelled.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    if ap.amount_paid > 0:
        flash('Cannot cancel an AP Voucher with payments applied. Reverse the payments first.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Cancellation reason must be at least 10 characters.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    try:
        _create_reversal_je(ap, reversal_date, current_user.id, label='Cancel')

        ap.status = 'cancelled'
        ap.cancelled_at = ph_now()
        ap.cancel_reason = cancel_reason
        db.session.commit()

        log_audit(
            module='accounts_payable',
            action='cancel',
            record_id=ap.id,
            record_identifier=f'{ap.ap_number} - {ap.vendor_name}',
            notes=f'Cancelled by {current_user.username}. Reason: {cancel_reason}'
        )

        flash(f'AP Voucher "{ap.ap_number}" cancelled. Reversal journal entry created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error cancelling purchase bill', exc_info=True)
        log_exception(e, severity='ERROR', module='accounts_payable.cancel')
        flash('An unexpected error occurred while cancelling the AP Voucher. Please '
              'try again; if it persists, contact your administrator.', 'error')

    return redirect(url_for('accounts_payable.view', id=id))


def _post_ap_je(ap, user_id):
    """Create and immediately post a purchase JE for a bill. Raises ValueError if required accounts missing."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    _accts = _get_gl_accounts()

    ap_account = _accts['ap']
    if not ap_account:
        raise ValueError("Accounts Payable - Trade (20101) not found in COA.")

    wt_account = None
    if ap.withholding_tax_amount and ap.withholding_tax_amount > 0:
        # Pre-check only: 20301 must exist as the WHT fallback account before
        # we build the JE lines. _wht_payable_buckets() below re-reads
        # _accts['wt'] itself (it needs it as the per-line fallback, not just
        # for this existence check), so wt_account isn't referenced again.
        wt_account = _accts['wt']
        if not wt_account:
            raise ValueError("WHT Payable - Expanded (20301) not found in COA.")

    # The JE mirrors the bill's lifecycle: created as a DRAFT while the bill
    # is a draft (so unposted vouchers never hit GL reports), promoted to
    # posted by the post route.
    je_status = 'posted' if ap.status == 'posted' else 'draft'
    entry_number = generate_entry_number(ap.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=ap.ap_date,
        description=f'Purchase Bill {ap.ap_number} — {ap.vendor_name}',
        reference=ap.ap_number,
        entry_type='purchase',
        branch_id=ap.branch_id,
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

    for item in ap.line_items:
        if not item.account_id:
            continue
        net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
        entry_line = JournalEntryLine(
            entry_id=je.id,
            line_number=line_num,
            account_id=item.account_id,
            description=item.description or '',
            debit_amount=net_base,
            credit_amount=Decimal('0.00')
        )
        db.session.add(entry_line)
        all_lines.append(entry_line)
        if first_expense_line is None:
            first_expense_line = entry_line
        line_num += 1

    for vat_acct, vat_amt in _input_vat_buckets(ap):
        if vat_amt <= 0:
            continue
        vat_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=vat_acct.id,
            description=f'Input VAT: {ap.ap_number}',
            debit_amount=vat_amt,
            credit_amount=Decimal('0.00')
        )
        db.session.add(vat_line)
        all_lines.append(vat_line)
        line_num += 1

    for wt_acct, wt_amt in _wht_payable_buckets(ap, _accts['wt']):
        wt_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_acct.id,
            description=f'WHT Payable: {ap.ap_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=wt_amt
        )
        db.session.add(wt_line)
        all_lines.append(wt_line)
        line_num += 1

    ap_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ap_account.id,
        description=f'AP: {ap.ap_number} — {ap.vendor_name}',
        debit_amount=Decimal('0.00'),
        credit_amount=Decimal(str(ap.total_amount))
    )
    db.session.add(ap_line)
    all_lines.append(ap_line)

    # Absorb rounding residual (and any VAT override difference) into the first
    # expense line so the JE always balances exactly
    sum_debits = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_credits = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    residual = sum_credits - sum_debits
    if residual != Decimal('0.00') and first_expense_line is not None:
        first_expense_line.debit_amount += residual

    db.session.flush()

    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"Purchase bill JE is not balanced "
            f"(debit={je.total_debit}, credit={je.total_credit}). "
            "Ensure every line item has an expense account assigned."
        )
    return je


def _create_reversal_je(ap, reversal_date, user_id, label='Cancel'):
    """Mirror the bill's stored JE with debits and credits swapped.

    Reverses exactly what was booked — per-category input VAT buckets,
    overrides, residual absorption and all (B-014). Raises ValueError if the
    bill has no stored journal entry to reverse.

    ``label`` prefixes each reversal line's description and forms the first
    six characters of the reference.

    Callers must pass a source JE (via ``ap.journal_entry``) that is not
    itself a reversal.
    """
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    source_je = ap.journal_entry
    if source_je is None:
        raise ValueError(
            f'Bill {ap.ap_number} has no stored journal entry to reverse. '
            f'Cannot {label.lower()}.')

    entry_number = generate_jv_number(ap.branch_id)  # reversal is a General Journal entry
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'Purchase Bill {label} — {ap.ap_number} (reversal)',
        reference=f'{label.upper()[:6]}-{ap.ap_number}',
        entry_type='reversal',
        is_reversing=True,
        reversed_entry_id=source_je.id,
        branch_id=ap.branch_id,
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
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=i,
            account_id=src.account_id,
            description=f'{label}: {src.description}' if src.description else label,
            debit_amount=src.credit_amount,
            credit_amount=src.debit_amount,
        ))
    db.session.flush()

    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f'Reversal JE is not balanced '
            f'(debit={je.total_debit}, credit={je.total_credit}).')

    # Link the source JE to its reversal. The source deliberately stays
    # 'posted' so the GL nets to zero (original + reversal both in the books).
    source_je.reversed_by_id = je.id

    return je


@accounts_payable_bp.route('/accounts-payable/<int:id>/void', methods=['POST'])
@login_required
@staff_or_above_required
def void(id):
    """Void a draft purchase bill (no journal entry — bill was never posted)."""
    ap = _get_ap_or_404(id)

    if ap.status != 'draft':
        flash('Only draft APVs can be voided.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid void date.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))

    try:
        # Delete the linked JE if it exists (JE was auto-created on save, even for drafts)
        if ap.journal_entry_id:
            from app.journal_entries.models import JournalEntry as _JE
            je_to_delete = db.session.get(_JE, ap.journal_entry_id)
            if je_to_delete:
                db.session.delete(je_to_delete)
            ap.journal_entry_id = None
            ap.journal_entry = None

        # Collect attachment file paths before deleting DB rows
        attachment_paths = []
        for att in list(ap.attachments):
            fp = os.path.join(
                current_app.config['UPLOAD_FOLDER'],
                'accounts_payable',
                str(ap.id),
                att.stored_filename
            )
            attachment_paths.append(fp)
            db.session.delete(att)

        ap.status = 'voided'
        ap.voided_at = ph_now()
        ap.voided_by_id = current_user.id
        ap.void_reason = void_reason
        db.session.commit()

        # Delete attachment files from disk after successful DB commit
        for fp in attachment_paths:
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except OSError:
                    current_app.logger.warning(f'Could not remove attachment file during void: {fp}')

        log_audit(
            module='accounts_payable',
            action='void',
            record_id=ap.id,
            record_identifier=f'{ap.ap_number} - {ap.vendor_name}',
            notes=f'Draft voided by {current_user.username} on {reversal_date}. Reason: {void_reason}. {len(attachment_paths)} attachment(s) deleted.'
        )

        flash(f'AP Voucher "{ap.ap_number}" voided.', 'warning')
    except Exception as e:
        from app.errors.utils import log_exception
        db.session.rollback()
        current_app.logger.error('Error voiding purchase bill', exc_info=True)
        log_exception(e, severity='ERROR', module='accounts_payable.void')
        flash('An unexpected error occurred while voiding the AP Voucher. Please '
              'try again; if it persists, contact your administrator.', 'error')

    return redirect(url_for('accounts_payable.view', id=id))


@accounts_payable_bp.route('/accounts-payable/<int:id>/attachments/upload', methods=['POST'])
@login_required
@staff_or_above_required
def upload_attachment(id):
    """Upload a file attachment to a draft AP Voucher (edit mode)."""
    ap = _get_ap_or_404(id)

    if ap.status != 'draft':
        flash('Attachments can only be uploaded while the APV is in draft status.', 'error')
        return redirect(url_for('accounts_payable.edit', id=id))

    uploaded_file = request.files.get('attachment')
    if not uploaded_file or uploaded_file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('accounts_payable.edit', id=id))

    ok, err = _save_ap_attachment(ap, uploaded_file, current_user)
    if ok:
        flash(f'File "{secure_filename(uploaded_file.filename)}" uploaded successfully.', 'success')
    else:
        flash(err, 'error')

    return redirect(url_for('accounts_payable.edit', id=id))


@accounts_payable_bp.route('/accounts-payable/attachments/<int:attachment_id>/download')
@login_required
def download_attachment(attachment_id):
    """Download a file attachment (all non-voided bill statuses)."""
    attachment = db.get_or_404(AccountsPayableAttachment, attachment_id)
    ap = _get_ap_or_404(attachment.ap_id)

    file_path = os.path.join(
        current_app.config['UPLOAD_FOLDER'],
        'accounts_payable',
        str(ap.id),
        attachment.stored_filename
    )

    if not os.path.isfile(file_path):
        flash('File not found on disk.', 'error')
        return redirect(url_for('accounts_payable.view', id=ap.id))

    response = send_file(
        file_path,
        mimetype=attachment.mime_type,
        as_attachment=True,
        download_name=attachment.original_filename
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@accounts_payable_bp.route('/accounts-payable/attachments/<int:attachment_id>/preview')
@login_required
def preview_attachment(attachment_id):
    """Serve an image attachment inline (for the popup modal img tag)."""
    attachment = db.get_or_404(AccountsPayableAttachment, attachment_id)

    if not attachment.is_image:
        abort(404)

    ap = _get_ap_or_404(attachment.ap_id)

    file_path = os.path.join(
        current_app.config['UPLOAD_FOLDER'],
        'accounts_payable',
        str(ap.id),
        attachment.stored_filename
    )

    if not os.path.isfile(file_path):
        abort(404)

    response = send_file(file_path, mimetype=attachment.mime_type, as_attachment=False)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@accounts_payable_bp.route('/accounts-payable/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete_attachment(attachment_id):
    """Delete a file attachment (draft status only)."""
    attachment = db.get_or_404(AccountsPayableAttachment, attachment_id)
    ap = _get_ap_or_404(attachment.ap_id)

    if ap.status != 'draft':
        flash('Attachments can only be deleted while the APV is in draft status.', 'error')
        return redirect(url_for('accounts_payable.edit', id=ap.id))

    file_path = os.path.join(
        current_app.config['UPLOAD_FOLDER'],
        'accounts_payable',
        str(ap.id),
        attachment.stored_filename
    )

    old_values = {
        'ap_id': ap.id,
        'original_filename': attachment.original_filename,
        'stored_filename': attachment.stored_filename,
        'mime_type': attachment.mime_type,
        'file_size': attachment.file_size,
    }
    original_name = attachment.original_filename

    try:
        db.session.delete(attachment)
        db.session.commit()

        if os.path.isfile(file_path):
            os.remove(file_path)

        log_delete(
            module='accounts_payable_attachment',
            record_id=attachment_id,
            record_identifier=f'{ap.ap_number} / {original_name}',
            old_values=old_values
        )

        flash(f'File "{original_name}" deleted.', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error deleting attachment: {e}', exc_info=True)
        flash('An unexpected error occurred while deleting the file. Please '
              'try again; if it persists, contact your administrator.', 'error')

    return redirect(url_for('accounts_payable.edit', id=ap.id))


def generate_ap_number():
    """
    Generate next bill number in format: AP-YYYY-MM-NNNN
    Example: AP-2026-06-0001 (resets each month)

    Voided bills keep their number (ap_number is unique; reissuing a
    voided number would collide), so the sequence counts ALL bills.
    """
    now = ph_now()
    prefix = f'AP-{now.year}-{now.month:02d}-'

    latest_ap = AccountsPayable.query.filter(
        AccountsPayable.ap_number.like(f'{prefix}%')
    ).order_by(AccountsPayable.ap_number.desc()).first()

    if latest_ap:
        try:
            last_num = int(latest_ap.ap_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f'{prefix}{next_num:04d}'
