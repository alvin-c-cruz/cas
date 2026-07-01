from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, jsonify, session, abort, current_app, send_file)
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem, SalesInvoiceAttachment
from app.sales_invoices.forms import SalesInvoiceForm
from app.customers.models import Customer
from app.customers.views import build_customer_quick_add_form
from app.sales_vat_categories.models import SalesVATCategory
from app.accounts.models import Account
from app.withholding_tax.models import WithholdingTax
from app.audit.utils import log_create, log_update, log_delete, model_to_dict, log_audit
from app.utils import ph_now
from app.utils.export import export_to_excel, export_to_csv
from app.utils.wt_labels import wt_label
from app.utils.cache_helpers import get_active_units, get_active_products
from app.journal_entries.utils import generate_entry_number, generate_jv_number
from app.settings import AppSettings
from app.periods.utils import validate_transaction_date_with_flash
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
import os
import uuid
from werkzeug.utils import secure_filename

sales_invoices_bp = Blueprint('sales_invoices', __name__, template_folder='templates')


def _customer_quick_add_whts():
    """Active WHT list for the inline Add-Customer modal (mirrors vendor quick-add)."""
    return WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()


# ---------------------------------------------------------------------------
# Role decorators
# ---------------------------------------------------------------------------

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


VALID_INVOICE_STATUSES = {'draft', 'posted', 'partially_paid', 'paid', 'voided', 'cancelled'}


# ---------------------------------------------------------------------------
# Branch guard
# ---------------------------------------------------------------------------

@sales_invoices_bp.before_request
def require_branch_selection():
    if current_user.is_authenticated and not session.get('selected_branch_id'):
        flash('Please select a branch to continue.', 'warning')
        return redirect(url_for('users.select_branch'))


# ---------------------------------------------------------------------------
# Non-JE helpers
# ---------------------------------------------------------------------------

def generate_invoice_number():
    """Plain continuous 5-digit sequence: 00001, 00002, ... No prefix, no reset.

    Each invoice gets the next number after the highest existing purely-numeric
    invoice_number. Legacy prefixed numbers (e.g. 'SI-2026-0030') are ignored, so
    new numbering starts cleanly at 00001 and never collides with old rows.
    """
    rows = SalesInvoice.query.with_entities(SalesInvoice.invoice_number).all()
    nums = [int(r[0]) for r in rows if r[0] and r[0].isdigit()]
    next_num = (max(nums) + 1) if nums else 1
    return f'{next_num:05d}'


def _get_invoice_or_404(id):
    invoice = db.get_or_404(SalesInvoice, id)
    if invoice.branch_id != session.get('selected_branch_id'):
        abort(404)
    return invoice


def _get_all_accounts_for_select():
    """Full COA for Choices.js account picker — groups marked non-selectable."""
    all_accts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in all_accts if a.parent_id is not None}
    id_map = {a.id: a for a in all_accts}

    def _depth(acct):
        d, p, visited = 0, acct.parent_id, set()
        while p and p in id_map and p not in visited:
            visited.add(p)
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


def _apply_overrides(invoice):
    """Apply manual VAT/WHT overrides from request.form. Returns redirect on error, None on success."""
    import decimal as _decimal
    vat_override = request.form.get('vat_override') == '1'
    wt_override = request.form.get('wt_override') == '1'
    invoice.vat_override = vat_override
    invoice.wt_override = wt_override
    if vat_override:
        try:
            vat_val = Decimal(request.form.get('vat_override_value', '0') or '0')
            if vat_val < 0 or (invoice.subtotal is not None and vat_val > invoice.subtotal):
                raise ValueError('out of range')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid VAT override value.', 'danger')
            return redirect(url_for('sales_invoices.list_invoices'))
        invoice.vat_amount = vat_val
    if wt_override:
        try:
            wt_val = Decimal(request.form.get('wt_override_value', '0') or '0')
            if wt_val < 0 or (invoice.subtotal is not None and wt_val > invoice.subtotal):
                raise ValueError('out of range')
        except (_decimal.InvalidOperation, ValueError):
            db.session.rollback()
            flash('Invalid withholding tax override value.', 'danger')
            return redirect(url_for('sales_invoices.list_invoices'))
        invoice.withholding_tax_amount = wt_val
    if vat_override or wt_override:
        invoice.total_amount = invoice.subtotal - invoice.withholding_tax_amount
        invoice.balance = invoice.total_amount - invoice.amount_paid
    return None


def _invoice_upload_dir(invoice_id):
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices', str(invoice_id))
    os.makedirs(path, exist_ok=True)
    return path


_ATTACHMENT_ALLOWED = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.csv': 'text/csv', '.txt': 'text/plain',
}

_EXPORT_COLUMNS = [
    'invoice_number', 'invoice_date', 'due_date', 'customer_name', 'customer_tin',
    'customer_po_number', 'subtotal', 'vat_amount', 'withholding_tax_amount',
    'total_amount', 'amount_paid', 'balance', 'status',
]

_EXPORT_HEADERS = [
    'Invoice #', 'Invoice Date', 'Due Date', 'Customer', 'TIN', 'Customer PO #',
    'Subtotal', 'VAT', 'Withholding Tax', 'Total', 'Paid', 'Balance', 'Status',
]

# ---------------------------------------------------------------------------
# JE helpers (Task 8) and route functions (Tasks 9-12) are appended below
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# JE helpers
# ---------------------------------------------------------------------------

def _get_gl_accounts():
    """Return AR-Trade (10201) and Creditable WHT Receivable (10212) accounts."""
    ar_acct = Account.query.filter_by(code='10201').first()
    wt_acct = Account.query.filter_by(code='10212').first()
    return {'ar': ar_acct, 'wt': wt_acct}


def _output_vat_buckets(invoice):
    """Group output VAT amounts by VATCategory.output_vat_account.

    Mirrors APV _input_vat_buckets() but reads output_vat_account.
    Returns sorted list of (Account, Decimal) pairs.
    Raises ValueError if a VAT-bearing line's category has no output_vat_account.
    """
    if Decimal(str(invoice.vat_amount)) <= 0:
        return []

    categories = {c.code: c for c in SalesVATCategory.query.all()}
    buckets = {}
    for item in invoice.line_items:
        vat_amt = Decimal(str(item.vat_amount or 0))
        if vat_amt <= 0:
            continue
        cat = categories.get(item.vat_category)
        acct = cat.output_vat_account if cat else None
        if acct is None:
            label = cat.code if cat else (item.vat_category or 'unknown')
            raise ValueError(
                f"VAT category '{label}' has no Output Tax account configured. "
                "Set it in VAT Categories before posting.")
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += vat_amt

    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    total = sum((amt for _, amt in ordered), Decimal('0.00'))
    override_diff = Decimal(str(invoice.vat_amount)) - total
    if override_diff != Decimal('0.00') and ordered:
        largest_id = max(ordered, key=lambda b: b[1])[0].id
        ordered = [
            (acct, amt + override_diff if acct.id == largest_id else amt)
            for acct, amt in ordered
        ]
    ordered = [(acct, amt) for acct, amt in ordered if amt != Decimal('0.00')]
    if any(amt < Decimal('0.00') for _, amt in ordered):
        raise ValueError(
            'VAT override is too far below the computed VAT to allocate '
            'across output tax accounts.')
    return ordered


def _consolidate_je(entries):
    """Merge JE preview lines posting to the same account into one row
    (sum debit and credit), preserving first-seen order. Several invoice
    lines crediting the same revenue account thus show that account once."""
    order, by_key = [], {}
    for e in entries:
        key = (e['code'], e['name'])
        if key not in by_key:
            by_key[key] = {'code': e['code'], 'name': e['name'],
                           'debit': Decimal('0.00'), 'credit': Decimal('0.00')}
            order.append(key)
        by_key[key]['debit'] += Decimal(str(e['debit']))
        by_key[key]['credit'] += Decimal(str(e['credit']))
    return [by_key[k] for k in order]


def _build_je_preview(invoice):
    """Return [{code, name, debit, credit}] for the detail view JE section,
    consolidated so each account appears once.

    If the invoice has a stored JE, read from it.
    If draft (no stored JE), compute what _post_invoice_je would produce.
    """
    if invoice.journal_entry:
        return _consolidate_je([
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in invoice.journal_entry.lines.all()
        ])

    # Draft preview: compute inline
    accts = _get_gl_accounts()
    entries = []

    # Credit revenue per line (net base)
    for item in invoice.line_items:
        if not item.account_id or not item.account:
            continue
        net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
        entries.append({
            'code': item.account.code,
            'name': item.account.name,
            'debit': Decimal('0.00'),
            'credit': net_base,
        })

    # Credit output VAT buckets
    try:
        vat_buckets = _output_vat_buckets(invoice)
    except ValueError as e:
        vat_buckets = []
        vat_amount = Decimal(str(invoice.vat_amount))
        if vat_amount > 0:
            entries.append({'code': '—', 'name': str(e),
                            'debit': Decimal('0.00'), 'credit': vat_amount})

    for vat_acct, vat_amt in vat_buckets:
        if vat_amt <= 0:
            continue
        entries.append({'code': vat_acct.code, 'name': vat_acct.name,
                        'debit': Decimal('0.00'), 'credit': vat_amt})

    # Debit Creditable WHT Receivable
    wt_amount = Decimal(str(invoice.withholding_tax_amount))
    if wt_amount > 0 and accts['wt']:
        entries.append({'code': accts['wt'].code, 'name': accts['wt'].name,
                        'debit': wt_amount, 'credit': Decimal('0.00')})

    # Debit Accounts Receivable
    if accts['ar']:
        entries.append({'code': accts['ar'].code, 'name': accts['ar'].name,
                        'debit': Decimal(str(invoice.total_amount)),
                        'credit': Decimal('0.00')})

    return _consolidate_je(entries)


# ---------------------------------------------------------------------------
# Journal Entry creation
# ---------------------------------------------------------------------------

def _post_invoice_je(invoice, user_id):
    """Create the sales JE. Reverse of APV: Dr AR + Dr Creditable WHT; Cr Revenue + Cr Output VAT."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    accts = _get_gl_accounts()
    ar_account = accts['ar']
    if not ar_account:
        raise ValueError("Accounts Receivable - Trade (10201) not found in COA.")

    wt_account = None
    if invoice.withholding_tax_amount and Decimal(str(invoice.withholding_tax_amount)) > 0:
        wt_account = accts['wt']
        if not wt_account:
            raise ValueError("Creditable Withholding Tax (10212) not found in COA. "
                             "Add this account before posting a sales invoice with WHT.")

    je_status = 'posted' if invoice.status == 'posted' else 'draft'
    entry_number = generate_entry_number(invoice.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=invoice.invoice_date,
        description=f'Sales Invoice {invoice.invoice_number} — {invoice.customer_name}',
        reference=invoice.invoice_number,
        entry_type='sale',
        branch_id=invoice.branch_id,
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

    # Order mirrors APV (debits first, then credits): AR, Creditable WHT, then
    # Output VAT and revenue. Amounts/balance are unchanged — only presentation.

    # Debit: Accounts Receivable (total receivable)
    ar_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ar_account.id,
        description=f'AR: {invoice.invoice_number} — {invoice.customer_name}',
        debit_amount=Decimal(str(invoice.total_amount)),
        credit_amount=Decimal('0.00'),
    )
    db.session.add(ar_line)
    all_lines.append(ar_line)
    line_num += 1

    # Debit: Creditable WHT Receivable
    if wt_account:
        wt_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_account.id,
            description=f'Creditable WHT: {invoice.invoice_number}',
            debit_amount=Decimal(str(invoice.withholding_tax_amount)),
            credit_amount=Decimal('0.00'),
        )
        db.session.add(wt_line)
        all_lines.append(wt_line)
        line_num += 1

    # Credit: output VAT per bucket
    for vat_acct, vat_amt in _output_vat_buckets(invoice):
        if vat_amt <= 0:
            continue
        vat_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=vat_acct.id,
            description=f'Output VAT: {invoice.invoice_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=vat_amt,
        )
        db.session.add(vat_line)
        all_lines.append(vat_line)
        line_num += 1

    # Credit: revenue accounts (net base per line item)
    for item in invoice.line_items:
        if not item.account_id:
            continue
        net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
        entry_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=item.account_id,
            description=item.description or '',
            debit_amount=Decimal('0.00'),
            credit_amount=net_base,
        )
        db.session.add(entry_line)
        all_lines.append(entry_line)
        if first_revenue_line is None:
            first_revenue_line = entry_line
        line_num += 1

    # Absorb rounding residual into first revenue line
    sum_debits = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_credits = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    residual = sum_debits - sum_credits
    if residual != Decimal('0.00') and first_revenue_line is not None:
        first_revenue_line.credit_amount += residual

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"Sales invoice JE is not balanced "
            f"(debit={je.total_debit}, credit={je.total_credit}). "
            "Ensure every line item has a revenue account assigned.")
    return je


def _create_reversal_je(invoice, reversal_date, user_id, label='Cancel'):
    """Swap debits/credits of the stored JE — used by cancel and void."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    source_je = invoice.journal_entry
    if source_je is None:
        raise ValueError(
            f'Invoice {invoice.invoice_number} has no stored journal entry to reverse.')

    entry_number = generate_jv_number(invoice.branch_id)  # reversal is a General Journal entry
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'Sales Invoice {label} — {invoice.invoice_number} (reversal)',
        reference=f'{label.upper()[:6]}-{invoice.invoice_number}',
        entry_type='reversal',
        is_reversing=True,
        reversed_entry_id=source_je.id,
        branch_id=invoice.branch_id,
        created_by_id=user_id,
        status='posted',
        posted_by_id=user_id,
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00'),
    )
    db.session.add(je)
    db.session.flush()

    source_lines = source_je.lines.all()
    if not source_lines:
        db.session.rollback()
        raise ValueError(
            f'Cannot reverse JE {source_je.entry_number}: it has no lines.')

    for i, src in enumerate(source_lines, start=1):
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=i,
            account_id=src.account_id,
            description=f'{label}: {src.description}' if src.description else label,
            debit_amount=src.credit_amount,   # swap
            credit_amount=src.debit_amount,   # swap
        ))
    db.session.flush()

    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Reversal JE is not balanced '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')

    # Link the source JE to its reversal
    source_je.reversed_by_id = je.id

    return je


# ---------------------------------------------------------------------------
# List helpers + routes
# ---------------------------------------------------------------------------

def _filtered_invoices_query(include_ids=False):
    current_branch_id = session.get('selected_branch_id')
    query = SalesInvoice.query.filter_by(branch_id=current_branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(SalesInvoice.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_INVOICE_STATUSES:
        query = query.filter_by(status=status_filter)

    customer_filter = request.args.get('customer_id', 'all')
    if customer_filter != 'all':
        try:
            query = query.filter_by(customer_id=int(customer_filter))
        except ValueError:
            pass

    q = request.args.get('q', '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(SalesInvoice.invoice_number.ilike(like),
                   SalesInvoice.customer_name.ilike(like))
        )

    year = ph_now().year
    date_from = request.args.get('date_from', f'{year}-01-01')
    if date_from:
        try:
            query = query.filter(SalesInvoice.invoice_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', f'{year}-12-31')
    if date_to:
        try:
            query = query.filter(SalesInvoice.invoice_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@sales_invoices_bp.route('/sales-invoices')
@login_required
def list_invoices():
    from app.sales_invoices.utils import compute_invoices_summary
    page = request.args.get('page', 1, type=int)
    per_page = 50
    query = _filtered_invoices_query().order_by(SalesInvoice.invoice_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    summary = compute_invoices_summary(session.get('selected_branch_id'))
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    return render_template(
        'sales_invoices/list.html',
        invoices=pagination.items,
        pagination=pagination,
        customers=customers,
        summary=summary,
        today=ph_now().date(),
        status_filter=request.args.get('status', 'all'),
        customer_filter=request.args.get('customer_id', 'all'),
        q=request.args.get('q', ''),
        date_from=request.args.get('date_from', f'{ph_now().year}-01-01'),
        date_to=request.args.get('date_to', f'{ph_now().year}-12-31'),
    )


@sales_invoices_bp.route('/sales-invoices/print')
@login_required
@staff_or_above_required
def print_list():
    invoices = (_filtered_invoices_query(include_ids=True)
                .order_by(SalesInvoice.invoice_date.desc()).all())
    company_name = AppSettings.get_setting('company_name') or ''
    return render_template(
        'sales_invoices/list_print.html',
        invoices=invoices,
        company_name=company_name,
        today=ph_now().date(),
        printed_at=ph_now(),
        status_filter=request.args.get('status', 'all'),
        date_from=request.args.get('date_from', f'{ph_now().year}-01-01'),
        date_to=request.args.get('date_to', f'{ph_now().year}-12-31'),
    )


@sales_invoices_bp.route('/sales-invoices/export/excel')
@login_required
@staff_or_above_required
def export_excel():
    invoices = (_filtered_invoices_query(include_ids=True)
                .order_by(SalesInvoice.invoice_date.desc()).all())
    log_audit('sales_invoice', 'export_excel', None, f'{len(invoices)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(data=invoices, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                           filename=f'sales_invoices_{timestamp}.xlsx',
                           title='Sales Invoices Report')


@sales_invoices_bp.route('/sales-invoices/export/csv')
@login_required
@staff_or_above_required
def export_csv_route():
    invoices = (_filtered_invoices_query(include_ids=True)
                .order_by(SalesInvoice.invoice_date.desc()).all())
    log_audit('sales_invoice', 'export_csv', None, f'{len(invoices)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(data=invoices, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                         filename=f'sales_invoices_{timestamp}.csv')


# ---------------------------------------------------------------------------
# Create and Edit routes
# ---------------------------------------------------------------------------

@sales_invoices_bp.route('/sales-invoices/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    form = SalesInvoiceForm()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    form.customer_id.choices = [(0, '-- Select Customer --')] + [
        (c.id, f'{c.code} - {c.name}') for c in customers]

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.invoice_date.data, 'Sales Invoice'):
            return render_template('sales_invoices/form.html', form=form, invoice=None,
                                   vat_categories=_vat_categories_for_form(),
                                   all_accounts=_get_all_accounts_for_select(),
                                   line_items=_submitted_line_items(),
                                   gl_accounts=_gl_accounts_dict(),
                                   wht_codes=_wht_codes_for_form(),
                                   units=_units_for_form(),
                                   products=_products_for_form(),
                                   customer_quick_add_form=build_customer_quick_add_form(),
                                   customer_quick_add_whts=_customer_quick_add_whts())
        try:
            cust = db.session.get(Customer, form.customer_id.data)
            if not cust:
                flash('Selected customer not found.', 'error')
                return render_template('sales_invoices/form.html', form=form, invoice=None,
                                       vat_categories=_vat_categories_for_form(),
                                       all_accounts=_get_all_accounts_for_select(),
                                       line_items=_submitted_line_items(),
                                       gl_accounts=_gl_accounts_dict(),
                                       wht_codes=_wht_codes_for_form(),
                                       units=_units_for_form(),
                                       products=_products_for_form(),
                                       customer_quick_add_form=build_customer_quick_add_form(),
                                       customer_quick_add_whts=_customer_quick_add_whts())

            line_err = _line_items_error(request.form.get('line_items', '[]'))
            if line_err:
                flash(line_err, 'error')
                return render_template('sales_invoices/form.html', form=form, invoice=None,
                                       vat_categories=_vat_categories_for_form(),
                                       all_accounts=_get_all_accounts_for_select(),
                                       line_items=_submitted_line_items(),
                                       gl_accounts=_gl_accounts_dict(),
                                       wht_codes=_wht_codes_for_form(),
                                       units=_units_for_form(),
                                       products=_products_for_form(),
                                       customer_quick_add_form=build_customer_quick_add_form(),
                                       customer_quick_add_whts=_customer_quick_add_whts())

            invoice = SalesInvoice(
                branch_id=session.get('selected_branch_id'),
                invoice_number=form.invoice_number.data,
                invoice_date=form.invoice_date.data,
                due_date=form.due_date.data,
                customer_id=cust.id,
                customer_name=cust.name,
                customer_tin=cust.tin,
                customer_address=cust.address,
                customer_po_number=form.customer_po_number.data or None,
                customer_po_date=form.customer_po_date.data or None,
                payment_terms=form.payment_terms.data,
                reference=form.reference.data,
                notes=form.notes.data or '',
                status='draft',
                amount_paid=Decimal('0.00'),
                balance=Decimal('0.00'),
                created_by_id=current_user.id,
            )
            _parse_and_attach_line_items(invoice, request.form.get('line_items', '[]'))
            invoice.calculate_totals()
            err = _apply_overrides(invoice)
            if err:
                return err

            db.session.add(invoice)
            db.session.flush()

            je = _post_invoice_je(invoice, current_user.id)
            invoice.journal_entry_id = je.id
            db.session.commit()

            log_create(
                module='sales_invoice',
                record_id=invoice.id,
                record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
                new_values=model_to_dict(invoice, [
                    'invoice_number', 'invoice_date', 'due_date', 'customer_name',
                    'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])
            )
            flash(f'Sales Invoice "{invoice.invoice_number}" entered successfully!', 'success')
            # Redirect to detail view; falls back to list if view route not yet registered
            try:
                return redirect(url_for('sales_invoices.view', id=invoice.id))
            except Exception:
                return redirect(url_for('sales_invoices.list_invoices'))

        except Exception as e:
            from app.errors.utils import log_exception
            db.session.rollback()
            current_app.logger.error('Error creating sales invoice', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_invoices.create')
            flash(f'Error entering Sales Invoice: {str(e)}', 'error')

    if request.method == 'GET':
        form.invoice_number.data = generate_invoice_number()
        form.invoice_date.data = ph_now().date()
        form.due_date.data = ph_now().date() + timedelta(days=30)

    return render_template('sales_invoices/form.html', form=form, invoice=None,
                           vat_categories=_vat_categories_for_form(),
                           all_accounts=_get_all_accounts_for_select(),
                           line_items=_submitted_line_items(),
                           gl_accounts=_gl_accounts_dict(),
                           wht_codes=_wht_codes_for_form(),
                           units=_units_for_form(),
                           products=_products_for_form(),
                           customer_quick_add_form=build_customer_quick_add_form(),
                           customer_quick_add_whts=_customer_quick_add_whts())


@sales_invoices_bp.route('/sales-invoices/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit(id):
    invoice = _get_invoice_or_404(id)
    if invoice.status != 'draft':
        flash('Only draft Sales Invoices can be edited.', 'error')
        try:
            return redirect(url_for('sales_invoices.view', id=id))
        except Exception:
            return redirect(url_for('sales_invoices.list_invoices'))

    form = SalesInvoiceForm(obj=invoice)
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    form.customer_id.choices = [(c.id, f'{c.code} - {c.name}') for c in customers]

    # On a failed POST, re-render with the user's SUBMITTED line items (preserve their edits);
    # on a GET, show the saved line items.
    restore_items = (_submitted_line_items() if request.method == 'POST'
                     else [item.to_dict() for item in invoice.line_items])

    if form.validate_on_submit():
        if not validate_transaction_date_with_flash(form.invoice_date.data, 'Sales Invoice'):
            return render_template('sales_invoices/form.html', form=form, invoice=invoice,
                                   vat_categories=_vat_categories_for_form(),
                                   all_accounts=_get_all_accounts_for_select(),
                                   line_items=restore_items,
                                   gl_accounts=_gl_accounts_dict(),
                                   wht_codes=_wht_codes_for_form(),
                                   units=_units_for_form(),
                                   products=_products_for_form(),
                                   customer_quick_add_form=build_customer_quick_add_form(),
                                   customer_quick_add_whts=_customer_quick_add_whts())
        try:
            old_values = model_to_dict(invoice, [
                'invoice_number', 'invoice_date', 'due_date', 'customer_name',
                'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])

            cust = db.session.get(Customer, form.customer_id.data)
            if not cust:
                flash('Selected customer not found.', 'error')
                return render_template('sales_invoices/form.html', form=form, invoice=invoice,
                                       vat_categories=_vat_categories_for_form(),
                                       all_accounts=_get_all_accounts_for_select(),
                                       line_items=restore_items,
                                       gl_accounts=_gl_accounts_dict(),
                                       wht_codes=_wht_codes_for_form(),
                                       units=_units_for_form(),
                                       products=_products_for_form(),
                                       customer_quick_add_form=build_customer_quick_add_form(),
                                       customer_quick_add_whts=_customer_quick_add_whts())

            line_err = _line_items_error(request.form.get('line_items', '[]'))
            if line_err:
                flash(line_err, 'error')
                return render_template('sales_invoices/form.html', form=form, invoice=invoice,
                                       vat_categories=_vat_categories_for_form(),
                                       all_accounts=_get_all_accounts_for_select(),
                                       line_items=restore_items,
                                       gl_accounts=_gl_accounts_dict(),
                                       wht_codes=_wht_codes_for_form(),
                                       units=_units_for_form(),
                                       products=_products_for_form(),
                                       customer_quick_add_form=build_customer_quick_add_form(),
                                       customer_quick_add_whts=_customer_quick_add_whts())

            invoice.invoice_number = form.invoice_number.data
            invoice.invoice_date = form.invoice_date.data
            invoice.due_date = form.due_date.data
            invoice.customer_id = cust.id
            invoice.customer_name = cust.name
            invoice.customer_tin = cust.tin
            invoice.customer_address = cust.address
            invoice.customer_po_number = form.customer_po_number.data or None
            invoice.customer_po_date = form.customer_po_date.data or None
            invoice.payment_terms = form.payment_terms.data
            invoice.reference = form.reference.data
            invoice.notes = form.notes.data or ''

            db.session.execute(db.delete(SalesInvoiceItem).where(SalesInvoiceItem.invoice_id == invoice.id))
            _parse_and_attach_line_items(invoice, request.form.get('line_items', '[]'),
                                         assign_invoice_id=True)
            # flush new rows to DB, then expire the collection so that
            # calculate_totals() and _post_invoice_je() reload fresh rows
            # rather than the stale pre-delete ORM cache (bulk deletes do
            # not evict the in-memory collection).
            db.session.flush()
            db.session.expire(invoice, ['line_items'])

            invoice.calculate_totals()
            err = _apply_overrides(invoice)
            if err:
                return err

            if invoice.journal_entry_id:
                from app.journal_entries.models import JournalEntry as _JE
                old_je_id = invoice.journal_entry_id
                invoice.journal_entry_id = None
                invoice.journal_entry = None
                db.session.flush()
                old_je = db.session.get(_JE, old_je_id)
                if old_je:
                    db.session.delete(old_je)
                db.session.flush()

            je = _post_invoice_je(invoice, current_user.id)
            invoice.journal_entry_id = je.id
            db.session.commit()

            new_values = model_to_dict(invoice, [
                'invoice_number', 'invoice_date', 'due_date', 'customer_name',
                'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])
            log_update(module='sales_invoice', record_id=invoice.id,
                       record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
                       old_values=old_values, new_values=new_values)

            flash(f'Sales Invoice "{invoice.invoice_number}" saved successfully!', 'success')
            # Redirect to detail view; falls back to list if view route not yet registered
            try:
                return redirect(url_for('sales_invoices.view', id=invoice.id))
            except Exception:
                return redirect(url_for('sales_invoices.list_invoices'))

        except Exception as e:
            from app.errors.utils import log_exception
            db.session.rollback()
            current_app.logger.error('Error updating sales invoice', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_invoices.edit')
            flash(f'Error saving Sales Invoice: {str(e)}', 'error')

    if request.method == 'GET':
        form.customer_id.data = invoice.customer_id

    return render_template('sales_invoices/form.html', form=form, invoice=invoice,
                           vat_categories=_vat_categories_for_form(),
                           all_accounts=_get_all_accounts_for_select(),
                           line_items=restore_items,
                           gl_accounts=_gl_accounts_dict(),
                           wht_codes=_wht_codes_for_form(),
                           units=_units_for_form(),
                           products=_products_for_form(),
                           customer_quick_add_form=build_customer_quick_add_form(),
                           customer_quick_add_whts=_customer_quick_add_whts())


# ── helpers called by create() and edit() ───────────────────────────────────

def _vat_categories_for_form():
    return [v.to_dict() for v in
            SalesVATCategory.query.filter_by(is_active=True).order_by(SalesVATCategory.code).all()]


def _gl_accounts_dict():
    _accts = _get_gl_accounts()
    return {
        'ar': {'code': _accts['ar'].code, 'name': _accts['ar'].name} if _accts['ar'] else None,
        'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
    }


def _wht_codes_for_form():
    codes = []
    for w in WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all():
        d = w.to_dict()
        d['label'] = wt_label(d, 'sales')
        codes.append(d)
    return codes


def _units_for_form():
    return [u.to_dict() for u in get_active_units()]


def _products_for_form():
    return [p.to_dict() for p in get_active_products()]


def _line_items_error(line_items_json):
    """Server-side validation of the raw line-items payload. Returns an error
    message string, or None when the lines are valid.

    Mirrors the create/edit form's client-side guard (Save stays disabled until a
    valid line exists) so the same rules hold when that guard is bypassed — every
    line needs a description, and the invoice must carry a positive total amount.
    """
    try:
        items = json.loads(line_items_json) if line_items_json else []
    except (json.JSONDecodeError, TypeError):
        items = []

    if not items:
        return 'Add at least one line item before saving the invoice.'

    total = Decimal('0')
    for item in items:
        if not str(item.get('description') or '').strip():
            return 'Each line item must have a description.'
        try:
            total += Decimal(str(item.get('amount') or '0'))
        except (InvalidOperation, ValueError):
            return 'Line item amounts must be valid numbers.'

    if total <= 0:
        return 'Enter an amount greater than zero on at least one line item.'

    return None


def _submitted_line_items():
    """Submitted line items (parsed) for re-rendering a failed POST without losing them.
    Returns [] when there is no submitted payload (e.g. a GET request)."""
    try:
        return json.loads(request.form.get('line_items') or '[]')
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_and_attach_line_items(invoice, line_items_json, assign_invoice_id=False):
    """Parse JSON line items string and attach SalesInvoiceItem objects to the invoice."""
    try:
        items = json.loads(line_items_json) if line_items_json else []
    except (json.JSONDecodeError, TypeError):
        items = []

    def _dec(v):
        try:
            return Decimal(str(v)) if v not in (None, '', 'null') else None
        except (InvalidOperation, TypeError):
            return None

    def _int(v):
        try:
            return int(v) if v and str(v).strip() not in ('', 'null') else None
        except (ValueError, TypeError):
            return None

    leaf_account_ids = {a['id'] for a in _get_all_accounts_for_select() if not a['is_group']}
    for idx, item_data in enumerate(items, start=1):
        vat_rate = Decimal('0.00')
        vat_category = item_data.get('vat_category') or None
        if vat_category:
            vat_cat = SalesVATCategory.query.filter_by(code=vat_category, is_active=True).first()
            if vat_cat:
                vat_rate = Decimal(str(vat_cat.rate))

        raw_wt_id = item_data.get('wt_id')
        wt_id = int(raw_wt_id) if raw_wt_id and str(raw_wt_id).strip() else None
        wt_rate = None
        if wt_id:
            wt_obj = db.session.get(WithholdingTax, wt_id)
            if wt_obj:
                wt_rate = wt_obj.rate

        raw_account_id = item_data.get('account_id')
        account_id = int(raw_account_id) if raw_account_id and str(raw_account_id).strip() else None
        if account_id and not db.session.get(Account, account_id):
            account_id = None
        if account_id is None:
            raise ValueError('Each line item must have an account assigned.')
        if account_id not in leaf_account_ids:
            raise ValueError('Each line item must use a valid, postable account.')

        line_item = SalesInvoiceItem(
            line_number=idx,
            description=item_data.get('description', ''),
            amount=Decimal(str(item_data.get('amount', '0') or '0')),
            quantity=_dec(item_data.get('quantity')),
            unit_price=_dec(item_data.get('unit_price')),
            uom_text=(item_data.get('uom_text') or None),
            unit_of_measure_id=_int(item_data.get('uom_id')),
            product_id=_int(item_data.get('product_id')),
            vat_category=vat_category,
            vat_rate=vat_rate,
            account_id=account_id,
            wt_id=wt_id,
            wt_rate=wt_rate,
        )
        if assign_invoice_id:
            line_item.invoice_id = invoice.id
        line_item.calculate_amounts()
        invoice.line_items.append(line_item)


# ---------------------------------------------------------------------------
# View / Post / Cancel / Void routes (Task 12)
# ---------------------------------------------------------------------------

@sales_invoices_bp.route('/sales-invoices/<int:id>')
@login_required
def view(id):
    invoice = _get_invoice_or_404(id)
    je_entries = _build_je_preview(invoice)
    sv_print_access = AppSettings.get_setting('sv_print_access', 'posted_only')
    return render_template('sales_invoices/detail.html', invoice=invoice,
                           je_entries=je_entries, sv_print_access=sv_print_access)


@sales_invoices_bp.route('/sales-invoices/<int:id>/post', methods=['POST'])
@login_required
@staff_or_above_required
def post(id):
    invoice = _get_invoice_or_404(id)
    if invoice.status != 'draft':
        flash('Only draft Sales Invoices can be posted.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))
    if not validate_transaction_date_with_flash(invoice.invoice_date, 'Sales Invoice'):
        return redirect(url_for('sales_invoices.view', id=id))
    try:
        invoice.status = 'posted'
        invoice.posted_by_id = current_user.id
        invoice.posted_at = ph_now()
        if invoice.journal_entry:
            invoice.journal_entry.status = 'posted'
            invoice.journal_entry.posted_by_id = current_user.id
            invoice.journal_entry.posted_at = ph_now()
        db.session.commit()
        log_audit('sales_invoice', 'post', invoice.id,
                  f'{invoice.invoice_number} - {invoice.customer_name}',
                  notes=f'Invoice posted by {current_user.username}')
        flash(f'Sales Invoice "{invoice.invoice_number}" posted successfully!', 'success')
    except Exception as e:
        from app.errors.utils import log_exception
        db.session.rollback()
        current_app.logger.error('Error posting sales invoice', exc_info=True)
        log_exception(e, severity='ERROR', module='sales_invoices.post')
        flash(f'Error posting Sales Invoice: {str(e)}', 'error')
    return redirect(url_for('sales_invoices.view', id=id))


@sales_invoices_bp.route('/sales-invoices/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    invoice = _get_invoice_or_404(id)
    if invoice.status != 'posted':
        flash('Only posted Sales Invoices can be cancelled.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))
    if invoice.amount_paid > 0:
        flash('Cannot cancel a Sales Invoice with payments applied. Reverse the payments first.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))
    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Cancellation reason must be at least 10 characters.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))
    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))
    if not validate_transaction_date_with_flash(reversal_date, 'Reversal'):
        return redirect(url_for('sales_invoices.view', id=id))
    try:
        _create_reversal_je(invoice, reversal_date, current_user.id, label='Cancel')
        invoice.status = 'cancelled'
        invoice.cancelled_at = ph_now()
        invoice.cancel_reason = cancel_reason
        db.session.commit()
        log_audit('sales_invoice', 'cancel', invoice.id,
                  f'{invoice.invoice_number} - {invoice.customer_name}',
                  notes=f'Cancelled by {current_user.username}. Reason: {cancel_reason}')
        flash(f'Sales Invoice "{invoice.invoice_number}" cancelled. Reversal JE created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        from app.errors.utils import log_exception
        db.session.rollback()
        current_app.logger.error('Error cancelling sales invoice', exc_info=True)
        log_exception(e, severity='ERROR', module='sales_invoices.cancel')
        flash(f'Error cancelling Sales Invoice: {str(e)}', 'error')
    return redirect(url_for('sales_invoices.view', id=id))


@sales_invoices_bp.route('/sales-invoices/<int:id>/void', methods=['POST'])
@login_required
@staff_or_above_required
def void(id):
    invoice = _get_invoice_or_404(id)
    if invoice.status != 'draft':
        flash('Only draft Sales Invoices can be voided.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))
    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))
    try:
        if invoice.journal_entry_id:
            from app.journal_entries.models import JournalEntry as _JE
            je_to_delete = db.session.get(_JE, invoice.journal_entry_id)
            if je_to_delete:
                db.session.delete(je_to_delete)
            invoice.journal_entry_id = None
            invoice.journal_entry = None

        attachment_paths = []
        for att in list(invoice.attachments):
            fp = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices',
                              str(invoice.id), att.stored_filename)
            attachment_paths.append(fp)
            db.session.delete(att)

        invoice.status = 'voided'
        invoice.voided_at = ph_now()
        invoice.voided_by_id = current_user.id
        invoice.void_reason = void_reason
        db.session.commit()

        for fp in attachment_paths:
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except OSError:
                    current_app.logger.warning(f'Could not remove attachment during void: {fp}')

        log_audit('sales_invoice', 'void', invoice.id,
                  f'{invoice.invoice_number} - {invoice.customer_name}',
                  notes=f'Draft voided by {current_user.username}. Reason: {void_reason}. {len(attachment_paths)} attachment(s) deleted.')
        flash(f'Sales Invoice "{invoice.invoice_number}" voided.', 'warning')
    except Exception as e:
        from app.errors.utils import log_exception
        db.session.rollback()
        current_app.logger.error('Error voiding sales invoice', exc_info=True)
        log_exception(e, severity='ERROR', module='sales_invoices.void')
        flash(f'Error voiding Sales Invoice: {str(e)}', 'error')
    return redirect(url_for('sales_invoices.view', id=id))


# ---------------------------------------------------------------------------
# Print + Attachment routes (Task 13)
# ---------------------------------------------------------------------------

@sales_invoices_bp.route('/sales-invoices/<int:id>/print')
@login_required
def print_invoice(id):
    invoice = _get_invoice_or_404(id)
    # Consolidated JE (each account once), same source as the detail-view Entry
    # table — keeps view/print in sync.
    je_entries = _build_je_preview(invoice)

    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('sales_invoices/print.html', invoice=invoice,
                           je_entries=je_entries, company=company, printed_at=ph_now())


@sales_invoices_bp.route('/sales-invoices/<int:id>/attachments/upload', methods=['POST'])
@login_required
@staff_or_above_required
def upload_attachment(id):
    invoice = _get_invoice_or_404(id)
    if invoice.status != 'draft':
        flash('Attachments can only be uploaded while the Sales Invoice is in draft status.', 'error')
        return redirect(url_for('sales_invoices.edit', id=id))
    uploaded_file = request.files.get('attachment')
    if not uploaded_file or uploaded_file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('sales_invoices.edit', id=id))
    original_name = secure_filename(uploaded_file.filename)
    if not original_name:
        flash('Invalid filename.', 'error')
        return redirect(url_for('sales_invoices.edit', id=id))
    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    mime_type = _ATTACHMENT_ALLOWED.get(ext)
    if mime_type is None:
        flash(f'File type "{ext or "unknown"}" is not allowed.', 'error')
        return redirect(url_for('sales_invoices.edit', id=id))
    stored_name = uuid.uuid4().hex + ext
    upload_dir = _invoice_upload_dir(id)
    file_path = os.path.join(upload_dir, stored_name)
    try:
        uploaded_file.save(file_path)
        file_size = os.path.getsize(file_path)
        attachment = SalesInvoiceAttachment(
            invoice_id=invoice.id, original_filename=original_name,
            stored_filename=stored_name, mime_type=mime_type,
            file_size=file_size, uploaded_by_id=current_user.id)
        db.session.add(attachment)
        db.session.commit()
        log_create('sales_invoice_attachment', attachment.id,
                   f'{invoice.invoice_number} / {original_name}',
                   new_values={'invoice_id': invoice.id, 'original_filename': original_name,
                               'mime_type': mime_type, 'file_size': file_size})
        flash(f'File "{original_name}" uploaded successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        if os.path.exists(file_path):
            os.remove(file_path)
        flash(f'Error uploading file: {str(e)}', 'error')
    return redirect(url_for('sales_invoices.edit', id=id))


@sales_invoices_bp.route('/sales-invoices/attachments/<int:attachment_id>/download')
@login_required
def download_attachment(attachment_id):
    attachment = db.get_or_404(SalesInvoiceAttachment, attachment_id)
    invoice = _get_invoice_or_404(attachment.invoice_id)
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices',
                             str(invoice.id), attachment.stored_filename)
    if not os.path.isfile(file_path):
        flash('File not found on disk.', 'error')
        return redirect(url_for('sales_invoices.view', id=invoice.id))
    response = send_file(file_path, mimetype=attachment.mime_type, as_attachment=True,
                         download_name=attachment.original_filename)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@sales_invoices_bp.route('/sales-invoices/attachments/<int:attachment_id>/preview')
@login_required
def preview_attachment(attachment_id):
    attachment = db.get_or_404(SalesInvoiceAttachment, attachment_id)
    if not attachment.is_image:
        abort(404)
    invoice = _get_invoice_or_404(attachment.invoice_id)
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices',
                             str(invoice.id), attachment.stored_filename)
    if not os.path.isfile(file_path):
        abort(404)
    response = send_file(file_path, mimetype=attachment.mime_type, as_attachment=False)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@sales_invoices_bp.route('/sales-invoices/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete_attachment(attachment_id):
    attachment = db.get_or_404(SalesInvoiceAttachment, attachment_id)
    invoice = _get_invoice_or_404(attachment.invoice_id)
    if invoice.status != 'draft':
        flash('Attachments can only be deleted while the Sales Invoice is in draft status.', 'error')
        return redirect(url_for('sales_invoices.edit', id=invoice.id))
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'sales_invoices',
                             str(invoice.id), attachment.stored_filename)
    old_values = {'invoice_id': invoice.id, 'original_filename': attachment.original_filename,
                  'mime_type': attachment.mime_type, 'file_size': attachment.file_size}
    original_name = attachment.original_filename
    try:
        db.session.delete(attachment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting file: {str(e)}', 'error')
        return redirect(url_for('sales_invoices.edit', id=invoice.id))
    # DB committed — now clean up disk and audit
    if os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            current_app.logger.warning(f'Could not remove attachment file: {file_path}')
    log_delete('sales_invoice_attachment', attachment_id,
               f'{invoice.invoice_number} / {original_name}', old_values=old_values)
    flash(f'File "{original_name}" deleted.', 'success')
    return redirect(url_for('sales_invoices.edit', id=invoice.id))
