from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, jsonify, session, abort, current_app, send_file)
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem, SalesInvoiceAttachment
from app.sales_invoices.forms import SalesInvoiceForm
from app.customers.models import Customer
from app.vat_categories.models import VATCategory
from app.accounts.models import Account
from app.withholding_tax.models import WithholdingTax
from app.audit.utils import log_create, log_update, log_delete, model_to_dict, log_audit
from app.utils import ph_now
from app.utils.export import export_to_excel, export_to_csv
from app.journal_entries.utils import generate_entry_number
from datetime import date, timedelta
from decimal import Decimal
import json
import os
import uuid
from werkzeug.utils import secure_filename

sales_invoices_bp = Blueprint('sales_invoices', __name__, template_folder='templates')


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
        if current_user.role not in ['accountant', 'admin']:
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
    """SI-YYYY-NNNN, annual reset. Uses PH time."""
    now = ph_now()
    prefix = f'SI-{now.year}-'
    latest = (SalesInvoice.query
              .filter(SalesInvoice.invoice_number.like(f'{prefix}%'))
              .order_by(SalesInvoice.invoice_number.desc())
              .first())
    if latest:
        try:
            next_num = int(latest.invoice_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    return f'{prefix}{next_num:04d}'


def _get_invoice_or_404(id):
    invoice = SalesInvoice.query.get_or_404(id)
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

    categories = {c.code: c for c in VATCategory.query.all()}
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


def _build_je_preview(invoice):
    """Return [{code, name, debit, credit}] for the detail view JE section.

    If the invoice has a stored JE, read from it.
    If draft (no stored JE), compute what _post_invoice_je would produce.
    """
    if invoice.journal_entry:
        return [
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in invoice.journal_entry.lines.all()
        ]

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

    return entries


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

    # Debit: Accounts Receivable
    ar_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ar_account.id,
        description=f'AR: {invoice.invoice_number} — {invoice.customer_name}',
        debit_amount=Decimal(str(invoice.total_amount)),
        credit_amount=Decimal('0.00'),
    )
    db.session.add(ar_line)
    all_lines.append(ar_line)

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

    entry_number = generate_entry_number(invoice.branch_id)
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

    for i, src in enumerate(source_je.lines.all(), start=1):
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

    customer_filter = request.args.get('customer', 'all')
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

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(SalesInvoice.invoice_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
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
        customer_filter=request.args.get('customer', 'all'),
        q=request.args.get('q', ''),
        date_from=request.args.get('date_from', ''),
        date_to=request.args.get('date_to', ''),
    )


@sales_invoices_bp.route('/sales-invoices/export/excel')
@login_required
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
def export_csv_route():
    invoices = (_filtered_invoices_query(include_ids=True)
                .order_by(SalesInvoice.invoice_date.desc()).all())
    log_audit('sales_invoice', 'export_csv', None, f'{len(invoices)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(data=invoices, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                         filename=f'sales_invoices_{timestamp}.csv')
