"""
Sales Invoice views for managing customer billing transactions.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, abort
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_invoices.forms import SalesInvoiceForm
from app.customers.models import Customer
from app.vat_categories.models import VATCategory
from app.accounts.models import Account
from app.audit.utils import log_create, log_update, log_delete, model_to_dict, log_audit
from app.utils import ph_now
from app.utils.export import export_to_excel, export_to_csv
from app.periods.utils import validate_transaction_date_with_flash
from app.journal_entries.utils import generate_entry_number
from datetime import datetime, date, timedelta
from decimal import Decimal
import json

sales_invoices_bp = Blueprint('sales_invoices', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can manage sales invoices.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


@sales_invoices_bp.before_request
def require_branch_selection():
    if current_user.is_authenticated and not session.get('selected_branch_id'):
        flash('Please select a branch to continue.', 'warning')
        return redirect(url_for('users.select_branch'))


def _get_invoice_or_404(id):
    invoice = SalesInvoice.query.get_or_404(id)
    if invoice.branch_id != session.get('selected_branch_id'):
        abort(404)
    return invoice


def generate_invoice_number():
    """
    Generate next invoice number in format: SI-YYYY-####
    Example: SI-2024-0001
    """
    current_year = datetime.now().year
    prefix = f'SI-{current_year}-'

    # Get the latest invoice for current year
    latest_invoice = SalesInvoice.query.filter(
        SalesInvoice.invoice_number.like(f'{prefix}%')
    ).order_by(SalesInvoice.invoice_number.desc()).first()

    if latest_invoice:
        # Extract the sequence number
        try:
            last_num = int(latest_invoice.invoice_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f'{prefix}{next_num:04d}'


@sales_invoices_bp.route('/sales-invoices')
@login_required
def list_invoices():
    """List all sales invoices."""
    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    customer_filter = request.args.get('customer', 'all')

    # Base query — scope to current branch
    current_branch_id = session.get('selected_branch_id')
    query = SalesInvoice.query.filter_by(branch_id=current_branch_id)

    # Apply filters
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    if customer_filter != 'all':
        try:
            customer_id = int(customer_filter)
            query = query.filter_by(customer_id=customer_id)
        except ValueError:
            pass

    # Order by invoice date (newest first)
    invoices = query.order_by(SalesInvoice.invoice_date.desc()).all()

    # Get customers for filter dropdown
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    return render_template('sales_invoices/list.html',
                         invoices=invoices,
                         customers=customers,
                         status_filter=status_filter,
                         customer_filter=customer_filter)


@sales_invoices_bp.route('/sales-invoices/export/excel')
@login_required
def export_excel():
    """Export sales invoices to Excel"""
    # Get filter parameters (same as list view)
    status_filter = request.args.get('status', 'all')
    customer_filter = request.args.get('customer', 'all')

    # Build query with same filters — scoped to current branch
    current_branch_id = session.get('selected_branch_id')
    query = SalesInvoice.query.filter_by(branch_id=current_branch_id)

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    if customer_filter != 'all':
        try:
            customer_id = int(customer_filter)
            query = query.filter_by(customer_id=customer_id)
        except ValueError:
            pass

    invoices = query.order_by(SalesInvoice.invoice_date.desc()).all()

    # Define columns and headers
    columns = [
        'invoice_number',
        'invoice_date',
        'due_date',
        'customer_name',
        'customer_tin',
        'subtotal',
        'vat_amount',
        'withholding_tax_amount',
        'total_amount',
        'amount_paid',
        'balance',
        'status'
    ]

    headers = [
        'Invoice #',
        'Invoice Date',
        'Due Date',
        'Customer',
        'TIN',
        'Subtotal',
        'VAT',
        'Withholding Tax',
        'Total',
        'Paid',
        'Balance',
        'Status'
    ]

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'sales_invoices_{timestamp}.xlsx'

    return export_to_excel(
        data=invoices,
        columns=columns,
        headers=headers,
        filename=filename,
        title='Sales Invoices Report'
    )


@sales_invoices_bp.route('/sales-invoices/export/csv')
@login_required
def export_csv_route():
    """Export sales invoices to CSV"""
    # Get filter parameters (same as list view)
    status_filter = request.args.get('status', 'all')
    customer_filter = request.args.get('customer', 'all')

    # Build query with same filters — scoped to current branch
    current_branch_id = session.get('selected_branch_id')
    query = SalesInvoice.query.filter_by(branch_id=current_branch_id)

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    if customer_filter != 'all':
        try:
            customer_id = int(customer_filter)
            query = query.filter_by(customer_id=customer_id)
        except ValueError:
            pass

    invoices = query.order_by(SalesInvoice.invoice_date.desc()).all()

    # Define columns and headers
    columns = [
        'invoice_number',
        'invoice_date',
        'due_date',
        'customer_name',
        'customer_tin',
        'subtotal',
        'vat_amount',
        'withholding_tax_amount',
        'total_amount',
        'amount_paid',
        'balance',
        'status'
    ]

    headers = [
        'Invoice #',
        'Invoice Date',
        'Due Date',
        'Customer',
        'TIN',
        'Subtotal',
        'VAT',
        'Withholding Tax',
        'Total',
        'Paid',
        'Balance',
        'Status'
    ]

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'sales_invoices_{timestamp}.csv'

    return export_to_csv(
        data=invoices,
        columns=columns,
        headers=headers,
        filename=filename
    )


@sales_invoices_bp.route('/sales-invoices/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new sales invoice."""
    form = SalesInvoiceForm()

    # Populate customer choices
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    form.customer_id.choices = [(0, '-- Select Customer --')] + [(c.id, f'{c.code} - {c.name}') for c in customers]

    if form.validate_on_submit():
        # Validate that the invoice date is not in a closed period
        if not validate_transaction_date_with_flash(form.invoice_date.data, 'sales invoice'):
            return render_template('sales_invoices/form.html', form=form, invoice=None)

        try:
            # Get customer details
            customer = Customer.query.get(form.customer_id.data)
            if not customer:
                flash('Selected customer not found.', 'error')
                return render_template('sales_invoices/form.html', form=form, invoice=None)

            # Create invoice
            invoice = SalesInvoice(
                branch_id=session.get('selected_branch_id'),
                invoice_number=form.invoice_number.data,
                invoice_date=form.invoice_date.data,
                due_date=form.due_date.data,
                customer_id=customer.id,
                customer_name=customer.name,
                customer_tin=customer.tin,
                customer_address=customer.address,
                payment_terms=form.payment_terms.data,
                reference=form.reference.data,
                notes=form.notes.data,
                status='draft',
                created_by_id=current_user.id
            )

            # Process line items from request
            line_items_data = request.form.getlist('line_items')
            if line_items_data:
                line_items = json.loads(line_items_data[0]) if line_items_data[0] else []

                for idx, item_data in enumerate(line_items, start=1):
                    # Get VAT rate from category
                    vat_rate = Decimal('0.00')
                    vat_category = item_data.get('vat_category')
                    if vat_category:
                        vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
                        if vat_cat:
                            vat_rate = Decimal(str(vat_cat.rate))

                    # Create line item
                    line_item = SalesInvoiceItem(
                        line_number=idx,
                        description=item_data.get('description', ''),
                        quantity=Decimal(str(item_data.get('quantity', 1))),
                        unit_price=Decimal(str(item_data.get('unit_price', 0))),
                        vat_category=vat_category,
                        vat_rate=vat_rate,
                        account_id=int(item_data.get('account_id')) if item_data.get('account_id') else None
                    )

                    # Calculate amounts
                    line_item.calculate_amounts()
                    invoice.line_items.append(line_item)

            # Calculate invoice totals
            invoice.calculate_totals()

            db.session.add(invoice)
            db.session.commit()

            # Audit log
            log_create(
                module='sales_invoice',
                record_id=invoice.id,
                record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
                new_values=model_to_dict(invoice, ['invoice_number', 'invoice_date', 'due_date', 'customer_name', 'subtotal', 'vat_amount', 'total_amount', 'status'])
            )

            flash(f'Sales Invoice "{invoice.invoice_number}" created successfully!', 'success')
            return redirect(url_for('sales_invoices.view', id=invoice.id))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating sales invoice", exc_info=True)
            log_exception(e, severity='ERROR', module='sales_invoices.create')
            db.session.rollback()
            flash(f'Error creating sales invoice: {str(e)}', 'error')

    # Set defaults for new invoice
    if request.method == 'GET':
        form.invoice_number.data = generate_invoice_number()
        form.invoice_date.data = date.today()
        form.due_date.data = date.today() + timedelta(days=30)

    # Get VAT categories and accounts for line items
    vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
    revenue_accounts = [a.to_dict() for a in Account.query.filter_by(account_type='Revenue').order_by(Account.code).all()]

    return render_template('sales_invoices/form.html',
                         form=form,
                         invoice=None,
                         vat_categories=vat_categories,
                         revenue_accounts=revenue_accounts)


@sales_invoices_bp.route('/sales-invoices/<int:id>')
@login_required
def view(id):
    """View sales invoice details."""
    invoice = _get_invoice_or_404(id)
    return render_template('sales_invoices/detail.html', invoice=invoice)


@sales_invoices_bp.route('/sales-invoices/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit(id):
    """Edit sales invoice (only drafts can be edited)."""
    invoice = _get_invoice_or_404(id)

    # Only drafts can be edited
    if invoice.status != 'draft':
        flash('Only draft invoices can be edited.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    form = SalesInvoiceForm(obj=invoice)

    # Populate customer choices
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    form.customer_id.choices = [(c.id, f'{c.code} - {c.name}') for c in customers]

    if form.validate_on_submit():
        # Validate that the invoice date is not in a closed period
        if not validate_transaction_date_with_flash(form.invoice_date.data, 'sales invoice'):
            return render_template('sales_invoices/form.html', form=form, invoice=invoice)

        try:
            # Capture old values
            old_values = model_to_dict(invoice, ['invoice_number', 'invoice_date', 'due_date', 'customer_name', 'subtotal', 'vat_amount', 'total_amount', 'status'])

            # Get customer details
            customer = Customer.query.get(form.customer_id.data)
            if not customer:
                flash('Selected customer not found.', 'error')
                return render_template('sales_invoices/form.html', form=form, invoice=invoice)

            # Update invoice header
            invoice.invoice_number = form.invoice_number.data
            invoice.invoice_date = form.invoice_date.data
            invoice.due_date = form.due_date.data
            invoice.customer_id = customer.id
            invoice.customer_name = customer.name
            invoice.customer_tin = customer.tin
            invoice.customer_address = customer.address
            invoice.payment_terms = form.payment_terms.data
            invoice.reference = form.reference.data
            invoice.notes = form.notes.data

            # Delete existing line items
            SalesInvoiceItem.query.filter_by(invoice_id=invoice.id).delete()

            # Process new line items
            line_items_data = request.form.getlist('line_items')
            if line_items_data:
                line_items = json.loads(line_items_data[0]) if line_items_data[0] else []

                for idx, item_data in enumerate(line_items, start=1):
                    # Get VAT rate from category
                    vat_rate = Decimal('0.00')
                    vat_category = item_data.get('vat_category')
                    if vat_category:
                        vat_cat = VATCategory.query.filter_by(code=vat_category, is_active=True).first()
                        if vat_cat:
                            vat_rate = Decimal(str(vat_cat.rate))

                    # Create line item
                    line_item = SalesInvoiceItem(
                        invoice_id=invoice.id,
                        line_number=idx,
                        description=item_data.get('description', ''),
                        quantity=Decimal(str(item_data.get('quantity', 1))),
                        unit_price=Decimal(str(item_data.get('unit_price', 0))),
                        vat_category=vat_category,
                        vat_rate=vat_rate,
                        account_id=int(item_data.get('account_id')) if item_data.get('account_id') else None
                    )

                    # Calculate amounts
                    line_item.calculate_amounts()
                    db.session.add(line_item)

            # Recalculate totals
            invoice.calculate_totals()

            db.session.commit()

            # Audit log
            new_values = model_to_dict(invoice, ['invoice_number', 'invoice_date', 'due_date', 'customer_name', 'subtotal', 'vat_amount', 'total_amount', 'status'])
            log_update(
                module='sales_invoice',
                record_id=invoice.id,
                record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
                old_values=old_values,
                new_values=new_values
            )

            flash(f'Sales Invoice "{invoice.invoice_number}" updated successfully!', 'success')
            return redirect(url_for('sales_invoices.view', id=invoice.id))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating sales invoice", exc_info=True)
            log_exception(e, severity='ERROR', module='sales_invoices.update')
            db.session.rollback()
            flash(f'Error updating sales invoice: {str(e)}', 'error')

    # Pre-populate form on GET
    if request.method == 'GET':
        form.customer_id.data = invoice.customer_id

    # Get VAT categories and accounts for line items
    vat_categories = [v.to_dict() for v in VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()]
    revenue_accounts = [a.to_dict() for a in Account.query.filter_by(account_type='Revenue').order_by(Account.code).all()]

    # Get existing line items
    line_items = [item.to_dict() for item in invoice.line_items.all()]

    return render_template('sales_invoices/form.html',
                         form=form,
                         invoice=invoice,
                         vat_categories=vat_categories,
                         revenue_accounts=revenue_accounts,
                         line_items=line_items)


@sales_invoices_bp.route('/sales-invoices/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post(id):
    """Post sales invoice (makes it final and immutable)."""
    invoice = _get_invoice_or_404(id)

    if invoice.status not in ('draft', 'sent'):
        flash('Only draft or sent invoices can be posted.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    try:
        invoice.status = 'posted'
        invoice.posted_by_id = current_user.id
        invoice.posted_at = ph_now()
        db.session.commit()

        # Audit log
        log_audit(
            module='sales_invoice',
            action='post',
            record_id=invoice.id,
            record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
            notes=f'Invoice posted by {current_user.username}'
        )

        flash(f'Sales Invoice "{invoice.invoice_number}" posted successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error posting sales invoice", exc_info=True)
        log_exception(e, severity='ERROR', module='sales_invoices.post')
        db.session.rollback()
        flash(f'Error posting invoice: {str(e)}', 'error')

    return redirect(url_for('sales_invoices.view', id=id))


def _create_invoice_void_je(invoice, reversal_date, user_id):
    """Create reversal JE when voiding a sales invoice. Raises ValueError if required accounts missing."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    ar_account = Account.query.filter_by(code='10201').first()
    if not ar_account:
        raise ValueError("Accounts Receivable - Trade (10201) not found in COA. Cannot void.")

    output_vat_account = None
    if invoice.vat_amount > 0:
        output_vat_account = Account.query.filter_by(code='20201').first()
        if not output_vat_account:
            raise ValueError("Output VAT - Sales (20201) not found in COA. Cannot void.")

    entry_number = generate_entry_number(invoice.branch_id)
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=reversal_date,
        description=f'Sales Invoice Void — {invoice.invoice_number} (reversal)',
        reference=f'VOID-{invoice.invoice_number}',
        entry_type='reversal',
        is_reversing=True,
        branch_id=invoice.branch_id,
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
    for item in invoice.line_items:
        if item.account_id and item.line_total > 0:
            db.session.add(JournalEntryLine(
                entry_id=je.id, line_number=line_num,
                account_id=item.account_id,
                description=item.description,
                debit_amount=item.line_total,
                credit_amount=Decimal('0.00')
            ))
            line_num += 1

    if output_vat_account:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=line_num,
            account_id=output_vat_account.id,
            description=f'Void Output VAT: {invoice.invoice_number}',
            debit_amount=invoice.vat_amount,
            credit_amount=Decimal('0.00')
        ))
        line_num += 1

    db.session.add(JournalEntryLine(
        entry_id=je.id, line_number=line_num,
        account_id=ar_account.id,
        description=f'Void AR: {invoice.invoice_number}',
        debit_amount=Decimal('0.00'),
        credit_amount=invoice.total_amount
    ))

    je.calculate_totals()
    return je


@sales_invoices_bp.route('/sales-invoices/<int:id>/send', methods=['POST'])
@login_required
@accountant_or_admin_required
def send(id):
    """Mark a draft invoice as sent to customer."""
    invoice = _get_invoice_or_404(id)

    if invoice.status != 'draft':
        flash('Only draft invoices can be marked as sent.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    try:
        invoice.status = 'sent'
        invoice.sent_at = ph_now()
        invoice.sent_by_id = current_user.id
        db.session.commit()

        log_audit(
            module='sales_invoice',
            action='send',
            record_id=invoice.id,
            record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
            notes=f'Marked as sent by {current_user.username}'
        )

        flash(f'Invoice "{invoice.invoice_number}" marked as sent.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error marking invoice as sent: {str(e)}', 'error')

    return redirect(url_for('sales_invoices.view', id=id))


@sales_invoices_bp.route('/sales-invoices/<int:id>/void', methods=['POST'])
@login_required
@accountant_or_admin_required
def void(id):
    """Void a posted sales invoice and create reversal journal entry."""
    from flask import current_app
    from app.errors.utils import log_exception
    invoice = _get_invoice_or_404(id)

    if invoice.status != 'posted':
        flash('Only posted invoices with no payments can be voided.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    if invoice.amount_paid > 0:
        flash('Cannot void an invoice with payments applied. Reverse the payments first.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    try:
        _create_invoice_void_je(invoice, reversal_date, current_user.id)

        invoice.status = 'voided'
        invoice.voided_at = ph_now()
        invoice.voided_by_id = current_user.id
        invoice.void_reason = void_reason
        db.session.commit()

        log_audit(
            module='sales_invoice',
            action='void',
            record_id=invoice.id,
            record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
            notes=f'Voided by {current_user.username}. Reason: {void_reason}'
        )

        flash(f'Sales Invoice "{invoice.invoice_number}" voided. Reversal journal entry created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("Error voiding sales invoice", exc_info=True)
        log_exception(e, severity='ERROR', module='sales_invoices.void')
        flash(f'Error voiding invoice: {str(e)}', 'error')

    return redirect(url_for('sales_invoices.view', id=id))


@sales_invoices_bp.route('/sales-invoices/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    """Cancel sales invoice."""
    invoice = _get_invoice_or_404(id)

    if invoice.status == 'cancelled':
        flash('Invoice is already cancelled.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    if invoice.amount_paid > 0:
        flash('Cannot cancel invoice with payments applied.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    try:
        invoice.status = 'cancelled'
        invoice.cancelled_at = ph_now()
        db.session.commit()

        # Audit log
        log_audit(
            module='sales_invoice',
            action='cancel',
            record_id=invoice.id,
            record_identifier=f'{invoice.invoice_number} - {invoice.customer_name}',
            notes=f'Invoice cancelled by {current_user.username}'
        )

        flash(f'Sales Invoice "{invoice.invoice_number}" cancelled.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error cancelling invoice: {str(e)}', 'error')

    return redirect(url_for('sales_invoices.view', id=id))


@sales_invoices_bp.route('/sales-invoices/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete sales invoice (only drafts can be deleted)."""
    invoice = _get_invoice_or_404(id)

    if invoice.status != 'draft':
        flash('Only draft invoices can be deleted.', 'error')
        return redirect(url_for('sales_invoices.view', id=id))

    try:
        # Capture values before delete
        old_values = model_to_dict(invoice, ['invoice_number', 'invoice_date', 'customer_name', 'total_amount', 'status'])
        invoice_number = invoice.invoice_number

        db.session.delete(invoice)
        db.session.commit()

        # Audit log
        log_delete(
            module='sales_invoice',
            record_id=id,
            record_identifier=f'{invoice_number}',
            old_values=old_values
        )

        flash(f'Sales Invoice "{invoice_number}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting invoice: {str(e)}', 'error')

    return redirect(url_for('sales_invoices.list_invoices'))
