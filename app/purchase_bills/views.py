"""
Purchase Bill views for managing supplier invoices and expenses.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, abort
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy.orm import selectinload
from app import db
from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
from app.purchase_bills.forms import PurchaseBillForm
from app.vendors.models import Vendor
from app.vat_categories.models import VATCategory
from app.accounts.models import Account
from app.withholding_tax.models import WithholdingTax
from app.audit.utils import log_create, log_update, model_to_dict, log_audit
from app.utils import ph_now
from app.utils.export import export_to_excel, export_to_csv
from app.periods.utils import validate_transaction_date_with_flash
from app.journal_entries.utils import generate_entry_number
from datetime import date, timedelta
from decimal import Decimal
import json

purchase_bills_bp = Blueprint('purchase_bills', __name__, template_folder='templates')


def _get_gl_accounts():
    """Return the three GL accounts used for purchase bill journal entries."""
    ap_acct = Account.query.filter_by(code='20101').first()
    input_vat_acct = Account.query.filter_by(code='10501').first()
    wt_gl_acct = Account.query.filter_by(code='20301').first()
    return {
        'ap': ap_acct,
        'input_vat': input_vat_acct,
        'wt': wt_gl_acct,
    }


def _build_je_preview(bill):
    """Return list of {code, name, debit, credit} dicts for the JE section.

    For posted bills reads from the stored JournalEntry. For drafts,
    computes the same entries the post route would create.
    """
    if bill.journal_entry:
        return [
            {
                'code': line.account.code if line.account else '—',
                'name': line.account.name if line.account else '—',
                'debit': line.debit_amount,
                'credit': line.credit_amount,
            }
            for line in bill.journal_entry.lines.all()
        ]

    accts = _get_gl_accounts()
    entries = []

    for item in bill.line_items:
        if not item.account_id or not item.account:
            continue
        net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
        entries.append({
            'code': item.account.code if item.account else '—',
            'name': item.account.name if item.account else '—',
            'debit': net_base,
            'credit': Decimal('0.00'),
        })

    vat_amount = Decimal(str(bill.vat_amount))
    if vat_amount > 0 and accts['input_vat']:
        entries.append({
            'code': accts['input_vat'].code,
            'name': accts['input_vat'].name,
            'debit': vat_amount,
            'credit': Decimal('0.00'),
        })

    wt_amount = Decimal(str(bill.withholding_tax_amount))
    if wt_amount > 0 and accts['wt']:
        entries.append({
            'code': accts['wt'].code,
            'name': accts['wt'].name,
            'debit': Decimal('0.00'),
            'credit': wt_amount,
        })

    if accts['ap']:
        entries.append({
            'code': accts['ap'].code,
            'name': accts['ap'].name,
            'debit': Decimal('0.00'),
            'credit': Decimal(str(bill.total_amount)),
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
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can manage purchase bills.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


VALID_BILL_STATUSES = {'draft', 'posted', 'partially_paid', 'paid', 'voided', 'cancelled'}


@purchase_bills_bp.before_request
def require_branch_selection():
    if current_user.is_authenticated and not session.get('selected_branch_id'):
        flash('Please select a branch to continue.', 'warning')
        return redirect(url_for('users.select_branch'))


def generate_bill_number():
    """
    Generate next bill number in format: AP-YYYY-MM-NNNN
    Example: AP-2026-06-0001 (resets each month)
    """
    now = ph_now()
    prefix = f'AP-{now.year}-{now.month:02d}-'

    latest_bill = PurchaseBill.query.filter(
        PurchaseBill.bill_number.like(f'{prefix}%'),
        PurchaseBill.status != 'voided'
    ).order_by(PurchaseBill.bill_number.desc()).first()

    if latest_bill:
        try:
            last_num = int(latest_bill.bill_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f'{prefix}{next_num:04d}'


def _get_bill_or_404(id):
    bill = PurchaseBill.query.get_or_404(id)
    if bill.branch_id != session.get('selected_branch_id'):
        abort(404)
    return bill


def _filtered_bills_query(include_ids=False):
    """Build a branch-scoped PurchaseBill query from request filter args.

    Args read: status, vendor, q, date_from, date_to — and ids when
    include_ids=True (exports only); a valid ids list overrides all
    other filters but stays branch-scoped. Invalid values are ignored.
    """
    current_branch_id = session.get('selected_branch_id')
    query = PurchaseBill.query.filter_by(branch_id=current_branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(PurchaseBill.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_BILL_STATUSES:
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
        query = query.filter(db.or_(PurchaseBill.bill_number.ilike(like),
                                    PurchaseBill.vendor_name.ilike(like)))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(PurchaseBill.bill_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(PurchaseBill.bill_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@purchase_bills_bp.route('/purchase-bills')
@login_required
def list_bills():
    """List purchase bills with summary cards, filters, search, pagination."""
    from app.purchase_bills.utils import compute_bills_summary

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = (_filtered_bills_query()
             .order_by(PurchaseBill.bill_date.desc()))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    summary = compute_bills_summary(session.get('selected_branch_id'))
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('purchase_bills/list.html',
                           bills=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           today=ph_now().date(),
                           status_filter=request.args.get('status', 'all'),
                           vendor_filter=request.args.get('vendor', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))


@purchase_bills_bp.route('/purchase-bills/export/excel')
@login_required
def export_excel():
    """Export purchase bills to Excel"""
    query = _filtered_bills_query(include_ids=True)

    bills = query.options(selectinload(PurchaseBill.line_items)).order_by(PurchaseBill.bill_date.desc()).all()

    columns = [
        'bill_number',
        'bill_date',
        'due_date',
        'vendor_name',
        'vendor_tin',
        'vendor_invoice_number',
        'subtotal',
        'vat_amount',
        'withholding_tax_amount',
        'total_amount',
        'amount_paid',
        'balance',
        'status'
    ]

    headers = [
        'Bill #',
        'Bill Date',
        'Due Date',
        'Vendor',
        'TIN',
        'Vendor Invoice #',
        'Subtotal',
        'VAT',
        'Withholding Tax',
        'Total',
        'Paid',
        'Balance',
        'Status'
    ]

    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    filename = f'purchase_bills_{timestamp}.xlsx'

    return export_to_excel(
        data=bills,
        columns=columns,
        headers=headers,
        filename=filename,
        title='Purchase Bills Report'
    )


@purchase_bills_bp.route('/purchase-bills/export/csv')
@login_required
def export_csv_route():
    """Export purchase bills to CSV"""
    query = _filtered_bills_query(include_ids=True)

    bills = query.options(selectinload(PurchaseBill.line_items)).order_by(PurchaseBill.bill_date.desc()).all()

    columns = [
        'bill_number',
        'bill_date',
        'due_date',
        'vendor_name',
        'vendor_tin',
        'vendor_invoice_number',
        'subtotal',
        'vat_amount',
        'withholding_tax_amount',
        'total_amount',
        'amount_paid',
        'balance',
        'status'
    ]

    headers = [
        'Bill #',
        'Bill Date',
        'Due Date',
        'Vendor',
        'TIN',
        'Vendor Invoice #',
        'Subtotal',
        'VAT',
        'Withholding Tax',
        'Total',
        'Paid',
        'Balance',
        'Status'
    ]

    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    filename = f'purchase_bills_{timestamp}.csv'

    return export_to_csv(
        data=bills,
        columns=columns,
        headers=headers,
        filename=filename
    )


@purchase_bills_bp.route('/purchase-bills/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new purchase bill."""
    form = PurchaseBillForm()

    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    form.vendor_id.choices = [(0, '-- Select Vendor --')] + [(v.id, f'{v.code} - {v.name}') for v in vendors]

    if form.validate_on_submit():
        # Validate that the bill date is not in a closed period
        if not validate_transaction_date_with_flash(form.bill_date.data, 'purchase bill'):
            return render_template('purchase_bills/form.html', form=form, bill=None)

        try:
            vendor = Vendor.query.get(form.vendor_id.data)
            if not vendor:
                flash('Selected vendor not found.', 'error')
                return render_template('purchase_bills/form.html', form=form, bill=None)

            bill = PurchaseBill(
                branch_id=session.get('selected_branch_id'),
                bill_number=form.bill_number.data,
                bill_date=form.bill_date.data,
                due_date=form.due_date.data,
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                vendor_tin=vendor.tin,
                vendor_address=vendor.address,
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

            line_items_data = request.form.getlist('line_items')
            if line_items_data:
                line_items = json.loads(line_items_data[0]) if line_items_data[0] else []

                for idx, item_data in enumerate(line_items, start=1):
                    vat_rate = Decimal('0.00')
                    vat_category = item_data.get('vat_category')
                    if vat_category:
                        vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
                        if vat_cat:
                            vat_rate = Decimal(str(vat_cat.rate))

                    wt_id = int(item_data['wt_id']) if item_data.get('wt_id') else None
                    wt_rate = None
                    if wt_id:
                        wt_obj = WithholdingTax.query.get(wt_id)
                        if wt_obj:
                            wt_rate = wt_obj.rate

                    line_item = PurchaseBillItem(
                        line_number=idx,
                        description=item_data.get('description', ''),
                        amount=Decimal(str(item_data.get('amount', 0))),
                        vat_category=vat_category,
                        vat_rate=vat_rate,
                        account_id=int(item_data.get('account_id')) if item_data.get('account_id') else None,
                        wt_id=wt_id,
                        wt_rate=wt_rate,
                    )
                    line_item.calculate_amounts()
                    bill.line_items.append(line_item)

            bill.calculate_totals()

            # Apply manual overrides
            import decimal as _decimal
            vat_override = request.form.get('vat_override') == '1'
            wt_override = request.form.get('wt_override') == '1'
            bill.vat_override = vat_override
            bill.wt_override = wt_override
            if vat_override:
                try:
                    vat_val = Decimal(request.form.get('vat_override_value', '0') or '0')
                    if vat_val < 0 or vat_val > bill.subtotal:
                        raise ValueError('out of range')
                except (_decimal.InvalidOperation, ValueError):
                    db.session.rollback()
                    flash('Invalid VAT override value.', 'danger')
                    return redirect(url_for('purchase_bills.list_bills'))
                bill.vat_amount = vat_val
            if wt_override:
                try:
                    wt_val = Decimal(request.form.get('wt_override_value', '0') or '0')
                    if wt_val < 0 or wt_val > bill.subtotal:
                        raise ValueError('out of range')
                except (_decimal.InvalidOperation, ValueError):
                    db.session.rollback()
                    flash('Invalid withholding tax override value.', 'danger')
                    return redirect(url_for('purchase_bills.list_bills'))
                bill.withholding_tax_amount = wt_val
            # Recompute net payable after potential overrides
            bill.total_amount = bill.subtotal - bill.withholding_tax_amount
            bill.balance = bill.total_amount - bill.amount_paid

            db.session.add(bill)
            db.session.flush()  # need bill.id before creating JE

            je = _post_bill_je(bill, current_user.id)
            bill.journal_entry_id = je.id
            db.session.commit()

            log_create(
                module='purchase_bill',
                record_id=bill.id,
                record_identifier=f'{bill.bill_number} - {bill.vendor_name}',
                new_values=model_to_dict(bill, ['bill_number', 'bill_date', 'due_date', 'vendor_name', 'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])
            )

            flash(f'Purchase Bill "{bill.bill_number}" created successfully!', 'success')
            return redirect(url_for('purchase_bills.view', id=bill.id))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating purchase bill", exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_bills.create')
            db.session.rollback()
            flash(f'Error creating purchase bill: {str(e)}', 'error')

    if request.method == 'GET':
        form.bill_number.data = generate_bill_number()
        form.bill_date.data = date.today()
        form.due_date.data = date.today() + timedelta(days=30)

    vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
    all_accounts = _get_all_accounts_for_select()

    _accts = _get_gl_accounts()
    gl_accounts = {
        'ap': {'code': _accts['ap'].code, 'name': _accts['ap'].name} if _accts['ap'] else None,
        'input_vat': {'code': _accts['input_vat'].code, 'name': _accts['input_vat'].name} if _accts['input_vat'] else None,
        'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
    }
    return render_template('purchase_bills/form.html',
                         form=form,
                         bill=None,
                         vat_categories=vat_categories,
                         all_accounts=all_accounts,
                         gl_accounts=gl_accounts)


@purchase_bills_bp.route('/purchase-bills/<int:id>')
@login_required
def view(id):
    """View purchase bill details."""
    bill = _get_bill_or_404(id)
    je_entries = _build_je_preview(bill)
    return render_template('purchase_bills/detail.html', bill=bill,
                           je_entries=je_entries)


@purchase_bills_bp.route('/purchase-bills/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit(id):
    """Edit purchase bill (only drafts can be edited)."""
    bill = _get_bill_or_404(id)

    if bill.status != 'draft':
        flash('Only draft bills can be edited.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    form = PurchaseBillForm(obj=bill)

    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    form.vendor_id.choices = [(v.id, f'{v.code} - {v.name}') for v in vendors]

    if form.validate_on_submit():
        # Validate that the bill date is not in a closed period
        if not validate_transaction_date_with_flash(form.bill_date.data, 'purchase bill'):
            return render_template('purchase_bills/form.html', form=form, bill=bill)

        try:
            old_values = model_to_dict(bill, ['bill_number', 'bill_date', 'due_date', 'vendor_name', 'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])

            vendor = Vendor.query.get(form.vendor_id.data)
            if not vendor:
                flash('Selected vendor not found.', 'error')
                return render_template('purchase_bills/form.html', form=form, bill=bill)

            bill.bill_number = form.bill_number.data
            bill.bill_date = form.bill_date.data
            bill.due_date = form.due_date.data
            bill.vendor_id = vendor.id
            bill.vendor_name = vendor.name
            bill.vendor_tin = vendor.tin
            bill.vendor_address = vendor.address
            bill.vendor_invoice_number = form.vendor_invoice_number.data
            bill.vendor_invoice_date = form.vendor_invoice_date.data
            bill.payment_terms = form.payment_terms.data
            bill.withholding_tax_rate = Decimal('0.00')
            bill.reference = form.reference.data
            bill.notes = form.notes.data

            PurchaseBillItem.query.filter_by(bill_id=bill.id).delete()

            line_items_data = request.form.getlist('line_items')
            if line_items_data:
                line_items = json.loads(line_items_data[0]) if line_items_data[0] else []

                for idx, item_data in enumerate(line_items, start=1):
                    vat_rate = Decimal('0.00')
                    vat_category = item_data.get('vat_category')
                    if vat_category:
                        vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
                        if vat_cat:
                            vat_rate = Decimal(str(vat_cat.rate))

                    wt_id = int(item_data['wt_id']) if item_data.get('wt_id') else None
                    wt_rate = None
                    if wt_id:
                        wt_obj = WithholdingTax.query.get(wt_id)
                        if wt_obj:
                            wt_rate = wt_obj.rate

                    line_item = PurchaseBillItem(
                        bill_id=bill.id,
                        line_number=idx,
                        description=item_data.get('description', ''),
                        amount=Decimal(str(item_data.get('amount', 0))),
                        vat_category=vat_category,
                        vat_rate=vat_rate,
                        account_id=int(item_data.get('account_id')) if item_data.get('account_id') else None,
                        wt_id=wt_id,
                        wt_rate=wt_rate,
                    )
                    line_item.calculate_amounts()
                    db.session.add(line_item)

            bill.calculate_totals()

            # Apply manual overrides
            import decimal as _decimal
            vat_override = request.form.get('vat_override') == '1'
            wt_override = request.form.get('wt_override') == '1'
            bill.vat_override = vat_override
            bill.wt_override = wt_override
            if vat_override:
                try:
                    vat_val = Decimal(request.form.get('vat_override_value', '0') or '0')
                    if vat_val < 0 or vat_val > bill.subtotal:
                        raise ValueError('out of range')
                except (_decimal.InvalidOperation, ValueError):
                    db.session.rollback()
                    flash('Invalid VAT override value.', 'danger')
                    return redirect(url_for('purchase_bills.list_bills'))
                bill.vat_amount = vat_val
            if wt_override:
                try:
                    wt_val = Decimal(request.form.get('wt_override_value', '0') or '0')
                    if wt_val < 0 or wt_val > bill.subtotal:
                        raise ValueError('out of range')
                except (_decimal.InvalidOperation, ValueError):
                    db.session.rollback()
                    flash('Invalid withholding tax override value.', 'danger')
                    return redirect(url_for('purchase_bills.list_bills'))
                bill.withholding_tax_amount = wt_val
            bill.total_amount = bill.subtotal - bill.withholding_tax_amount
            bill.balance = bill.total_amount - bill.amount_paid

            # Delete old JE and create a fresh one
            if bill.journal_entry_id:
                from app.journal_entries.models import JournalEntry as _JE
                old_je_id_to_delete = bill.journal_entry_id
                bill.journal_entry_id = None
                bill.journal_entry = None
                db.session.flush()  # commit FK null before deleting the JE row
                old_je = db.session.get(_JE, old_je_id_to_delete)
                if old_je:
                    db.session.delete(old_je)

            db.session.flush()

            je = _post_bill_je(bill, current_user.id)
            bill.journal_entry_id = je.id
            db.session.commit()

            new_values = model_to_dict(bill, ['bill_number', 'bill_date', 'due_date', 'vendor_name', 'subtotal', 'vat_amount', 'withholding_tax_amount', 'total_amount', 'status'])
            log_update(
                module='purchase_bill',
                record_id=bill.id,
                record_identifier=f'{bill.bill_number} - {bill.vendor_name}',
                old_values=old_values,
                new_values=new_values
            )

            flash(f'Purchase Bill "{bill.bill_number}" updated successfully!', 'success')
            return redirect(url_for('purchase_bills.view', id=bill.id))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating purchase bill", exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_bills.update')
            db.session.rollback()
            flash(f'Error updating purchase bill: {str(e)}', 'error')

    if request.method == 'GET':
        form.vendor_id.data = bill.vendor_id

    vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
    all_accounts = _get_all_accounts_for_select()
    line_items = [item.to_dict() for item in bill.line_items]

    _accts = _get_gl_accounts()
    gl_accounts = {
        'ap': {'code': _accts['ap'].code, 'name': _accts['ap'].name} if _accts['ap'] else None,
        'input_vat': {'code': _accts['input_vat'].code, 'name': _accts['input_vat'].name} if _accts['input_vat'] else None,
        'wt': {'code': _accts['wt'].code, 'name': _accts['wt'].name} if _accts['wt'] else None,
    }
    return render_template('purchase_bills/form.html',
                         form=form,
                         bill=bill,
                         vat_categories=vat_categories,
                         all_accounts=all_accounts,
                         line_items=line_items,
                         gl_accounts=gl_accounts)


@purchase_bills_bp.route('/purchase-bills/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post(id):
    """Post purchase bill (makes it final)."""
    bill = _get_bill_or_404(id)

    if bill.status != 'draft':
        flash('Only draft bills can be posted.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    try:
        bill.status = 'posted'
        bill.posted_by_id = current_user.id
        bill.posted_at = ph_now()
        db.session.commit()

        log_audit(
            module='purchase_bill',
            action='post',
            record_id=bill.id,
            record_identifier=f'{bill.bill_number} - {bill.vendor_name}',
            notes=f'Bill posted by {current_user.username}'
        )

        flash(f'Purchase Bill "{bill.bill_number}" posted successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error posting purchase bill", exc_info=True)
        log_exception(e, severity='ERROR', module='purchase_bills.post')
        db.session.rollback()
        flash(f'Error posting bill: {str(e)}', 'error')

    return redirect(url_for('purchase_bills.view', id=id))


@purchase_bills_bp.route('/purchase-bills/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    """Cancel a posted purchase bill and create a reversal journal entry."""
    from flask import current_app
    from app.errors.utils import log_exception
    bill = _get_bill_or_404(id)

    if bill.status != 'posted':
        flash('Only posted bills can be cancelled.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    if bill.amount_paid > 0:
        flash('Cannot cancel a bill with payments applied. Reverse the payments first.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Cancellation reason must be at least 10 characters.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    try:
        _create_reversal_je(bill, reversal_date, current_user.id, label='Cancel')

        bill.status = 'cancelled'
        bill.cancelled_at = ph_now()
        bill.cancel_reason = cancel_reason
        db.session.commit()

        log_audit(
            module='purchase_bill',
            action='cancel',
            record_id=bill.id,
            record_identifier=f'{bill.bill_number} - {bill.vendor_name}',
            notes=f'Cancelled by {current_user.username}. Reason: {cancel_reason}'
        )

        flash(f'Purchase Bill "{bill.bill_number}" cancelled. Reversal journal entry created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error cancelling purchase bill', exc_info=True)
        log_exception(e, severity='ERROR', module='purchase_bills.cancel')
        flash(f'Error cancelling bill: {str(e)}', 'error')

    return redirect(url_for('purchase_bills.view', id=id))


def _post_bill_je(bill, user_id):
    """Create and immediately post a purchase JE for a bill. Raises ValueError if required accounts missing."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    _accts = _get_gl_accounts()

    ap_account = _accts['ap']
    if not ap_account:
        raise ValueError("Accounts Payable - Trade (20101) not found in COA.")

    input_vat_account = None
    if bill.vat_amount and bill.vat_amount > 0:
        input_vat_account = _accts['input_vat']
        if not input_vat_account:
            raise ValueError("Input VAT - Current (10501) not found in COA.")

    wt_account = None
    if bill.withholding_tax_amount and bill.withholding_tax_amount > 0:
        wt_account = _accts['wt']
        if not wt_account:
            raise ValueError("WHT Payable - Expanded (20301) not found in COA.")

    entry_number = generate_entry_number(bill.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=bill.bill_date,
        description=f'Purchase Bill {bill.bill_number} — {bill.vendor_name}',
        reference=bill.bill_number,
        entry_type='purchase',
        branch_id=bill.branch_id,
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

    vat_used = Decimal(str(bill.vat_amount))

    line_num = 1
    first_expense_line = None
    all_lines = []

    for item in bill.line_items:
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

    if input_vat_account:
        vat_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=input_vat_account.id,
            description=f'Input VAT: {bill.bill_number}',
            debit_amount=vat_used,
            credit_amount=Decimal('0.00')
        )
        db.session.add(vat_line)
        all_lines.append(vat_line)
        line_num += 1

    if wt_account:
        wt_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_account.id,
            description=f'WHT Payable: {bill.bill_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=Decimal(str(bill.withholding_tax_amount))
        )
        db.session.add(wt_line)
        all_lines.append(wt_line)
        line_num += 1

    ap_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ap_account.id,
        description=f'AP: {bill.bill_number} — {bill.vendor_name}',
        debit_amount=Decimal('0.00'),
        credit_amount=Decimal(str(bill.total_amount))
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


def _create_reversal_je(bill, reversal_date, user_id, label='Void'):
    """Create reversal JE when voiding or cancelling a purchase bill. Raises ValueError if required accounts missing."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    ap_account = Account.query.filter_by(code='20101').first()
    if not ap_account:
        raise ValueError(f"Accounts Payable - Trade (20101) not found in COA. Cannot {label.lower()}.")

    input_vat_account = None
    if bill.vat_amount > 0:
        input_vat_account = Account.query.filter_by(code='10501').first()
        if not input_vat_account:
            raise ValueError(f"Input VAT - Current (10501) not found in COA. Cannot {label.lower()}.")

    wt_account = None
    if bill.withholding_tax_amount > 0:
        wt_account = Account.query.filter_by(code='20301').first()
        if not wt_account:
            raise ValueError(f"Withholding Tax Payable - Expanded (20301) not found in COA. Cannot {label.lower()}.")

    entry_number = generate_entry_number(bill.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'Purchase Bill {label} — {bill.bill_number} (reversal)',
        reference=f'{label.upper()[:6]}-{bill.bill_number}',
        entry_type='reversal',
        is_reversing=True,
        branch_id=bill.branch_id,
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

    line_num = 1
    all_lines = []
    ap_line = JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ap_account.id,
        description=f'{label} AP: {bill.bill_number}',
        debit_amount=bill.total_amount,
        credit_amount=Decimal('0.00')
    )
    db.session.add(ap_line)
    all_lines.append(ap_line)
    line_num += 1

    if wt_account:
        wt_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=wt_account.id,
            description=f'{label} WT: {bill.bill_number}',
            debit_amount=bill.withholding_tax_amount,
            credit_amount=Decimal('0.00')
        )
        db.session.add(wt_line)
        all_lines.append(wt_line)
        line_num += 1

    first_expense_reversal = None
    for item in bill.line_items:
        if item.account_id and item.line_total > 0:
            net_base = Decimal(str(item.line_total)) - Decimal(str(item.vat_amount))
            entry_line = JournalEntryLine(
                entry_id=je.id, line_number=line_num,
                account_id=item.account_id,
                description=item.description,
                debit_amount=Decimal('0.00'),
                credit_amount=net_base
            )
            db.session.add(entry_line)
            all_lines.append(entry_line)
            if first_expense_reversal is None:
                first_expense_reversal = entry_line
            line_num += 1

    if input_vat_account:
        vat_line = JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=input_vat_account.id,
            description=f'{label} Input VAT: {bill.bill_number}',
            debit_amount=Decimal('0.00'),
            credit_amount=bill.vat_amount
        )
        db.session.add(vat_line)
        all_lines.append(vat_line)

    # Absorb rounding residual (and any VAT override difference) into the first
    # expense line so the reversal JE always balances exactly
    sum_debits = sum((l.debit_amount for l in all_lines), Decimal('0.00'))
    sum_credits = sum((l.credit_amount for l in all_lines), Decimal('0.00'))
    residual = sum_debits - sum_credits
    if residual != Decimal('0.00') and first_expense_reversal is not None:
        first_expense_reversal.credit_amount += residual

    db.session.flush()

    je.calculate_totals()
    return je


@purchase_bills_bp.route('/purchase-bills/<int:id>/void', methods=['POST'])
@login_required
@accountant_or_admin_required
def void(id):
    """Void a draft purchase bill (no journal entry — bill was never posted)."""
    bill = _get_bill_or_404(id)

    if bill.status != 'draft':
        flash('Only draft bills can be voided.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid void date.', 'error')
        return redirect(url_for('purchase_bills.view', id=id))

    try:
        # Delete the linked JE if it exists (JE was auto-created on save, even for drafts)
        if bill.journal_entry_id:
            from app.journal_entries.models import JournalEntry as _JE
            je_to_delete = db.session.get(_JE, bill.journal_entry_id)
            if je_to_delete:
                db.session.delete(je_to_delete)
            bill.journal_entry_id = None
            bill.journal_entry = None

        bill.status = 'voided'
        bill.voided_at = ph_now()
        bill.voided_by_id = current_user.id
        bill.void_reason = void_reason
        db.session.commit()

        log_audit(
            module='purchase_bill',
            action='void',
            record_id=bill.id,
            record_identifier=f'{bill.bill_number} - {bill.vendor_name}',
            notes=f'Draft voided by {current_user.username} on {reversal_date}. Reason: {void_reason}'
        )

        flash(f'Purchase Bill "{bill.bill_number}" voided.', 'warning')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        db.session.rollback()
        current_app.logger.error('Error voiding purchase bill', exc_info=True)
        log_exception(e, severity='ERROR', module='purchase_bills.void')
        flash(f'Error voiding bill: {str(e)}', 'error')

    return redirect(url_for('purchase_bills.view', id=id))


