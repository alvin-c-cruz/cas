"""
Receipt/Payment views for managing cash and bank transactions.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.receipts.models import Receipt
from app.receipts.forms import ReceiptForm
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.audit.utils import log_create, log_update, log_delete, model_to_dict, log_audit
from app.utils import ph_now
from datetime import datetime, date
from decimal import Decimal

receipts_bp = Blueprint('receipts', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can manage receipts/payments.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def generate_receipt_number(transaction_type):
    """
    Generate next receipt number.
    Collections: CR-YYYY-#### (Customer Receipt)
    Payments: CP-YYYY-#### (Cash Payment / Check Payment)
    """
    current_year = datetime.now().year
    prefix = f'CR-{current_year}-' if transaction_type == 'collection' else f'CP-{current_year}-'

    latest_receipt = Receipt.query.filter(
        Receipt.receipt_number.like(f'{prefix}%'),
        Receipt.transaction_type == transaction_type
    ).order_by(Receipt.receipt_number.desc()).first()

    if latest_receipt:
        try:
            last_num = int(latest_receipt.receipt_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f'{prefix}{next_num:04d}'


@receipts_bp.route('/receipts')
@login_required
def list_receipts():
    """List all receipts/payments."""
    type_filter = request.args.get('type', 'all')
    method_filter = request.args.get('method', 'all')
    status_filter = request.args.get('status', 'all')

    query = Receipt.query

    if type_filter != 'all':
        query = query.filter_by(transaction_type=type_filter)

    if method_filter != 'all':
        query = query.filter_by(payment_method=method_filter)

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    receipts = query.order_by(Receipt.receipt_date.desc()).all()

    return render_template('receipts/list.html',
                         receipts=receipts,
                         type_filter=type_filter,
                         method_filter=method_filter,
                         status_filter=status_filter)


@receipts_bp.route('/receipts/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new receipt/payment."""
    form = ReceiptForm()

    # Populate dropdowns
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    cash_bank_accounts = Account.query.filter(
        Account.account_type.in_(['Asset']),
        Account.name.like('%Cash%') | Account.name.like('%Bank%')
    ).order_by(Account.code).all()

    form.customer_id.choices = [(0, '-- Select Customer --')] + [(c.id, f'{c.code} - {c.name}') for c in customers]
    form.vendor_id.choices = [(0, '-- Select Vendor --')] + [(v.id, f'{v.code} - {v.name}') for v in vendors]
    form.account_id.choices = [(0, '-- Select Account --')] + [(a.id, f'{a.code} - {a.name}') for a in cash_bank_accounts]

    if form.validate_on_submit():
        try:
            # Validate transaction type selection
            if form.transaction_type.data == 'collection':
                if not form.customer_id.data or form.customer_id.data == 0:
                    flash('Please select a customer for collection.', 'error')
                    return render_template('receipts/form.html', form=form, receipt=None)
                customer = Customer.query.get(form.customer_id.data)
                customer_id = customer.id
                customer_name = customer.name
                vendor_id = None
                vendor_name = None
            else:  # payment
                if not form.vendor_id.data or form.vendor_id.data == 0:
                    flash('Please select a vendor for payment.', 'error')
                    return render_template('receipts/form.html', form=form, receipt=None)
                vendor = Vendor.query.get(form.vendor_id.data)
                vendor_id = vendor.id
                vendor_name = vendor.name
                customer_id = None
                customer_name = None

            receipt = Receipt(
                receipt_number=form.receipt_number.data,
                receipt_date=form.receipt_date.data,
                transaction_type=form.transaction_type.data,
                customer_id=customer_id,
                customer_name=customer_name,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                payment_method=form.payment_method.data,
                check_number=form.check_number.data if form.payment_method.data == 'check' else None,
                check_date=form.check_date.data if form.payment_method.data == 'check' else None,
                check_bank=form.check_bank.data if form.payment_method.data == 'check' else None,
                bank_account=form.bank_account.data,
                account_id=form.account_id.data if form.account_id.data else None,
                amount=form.amount.data,
                reference=form.reference.data,
                notes=form.notes.data,
                status='draft',
                created_by_id=current_user.id
            )

            db.session.add(receipt)
            db.session.commit()

            log_create(
                module='receipt',
                record_id=receipt.id,
                record_identifier=f'{receipt.receipt_number} - {customer_name or vendor_name}',
                new_values=model_to_dict(receipt, ['receipt_number', 'receipt_date', 'transaction_type', 'payment_method', 'amount', 'status'])
            )

            flash(f'{"Receipt" if receipt.transaction_type == "collection" else "Payment"} "{receipt.receipt_number}" created successfully!', 'success')
            return redirect(url_for('receipts.view', id=receipt.id))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating receipt/payment", exc_info=True)
            log_exception(e, severity='ERROR', module='receipts.create')
            db.session.rollback()
            flash(f'Error creating receipt/payment: {str(e)}', 'error')

    if request.method == 'GET':
        # Get transaction type from query param
        transaction_type = request.args.get('type', 'collection')
        form.transaction_type.data = transaction_type
        form.receipt_number.data = generate_receipt_number(transaction_type)
        form.receipt_date.data = date.today()

    return render_template('receipts/form.html', form=form, receipt=None)


@receipts_bp.route('/receipts/<int:id>')
@login_required
def view(id):
    """View receipt/payment details."""
    receipt = Receipt.query.get_or_404(id)
    return render_template('receipts/detail.html', receipt=receipt)


@receipts_bp.route('/receipts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit(id):
    """Edit receipt/payment (only drafts can be edited)."""
    receipt = Receipt.query.get_or_404(id)

    if receipt.status != 'draft':
        flash('Only draft receipts/payments can be edited.', 'error')
        return redirect(url_for('receipts.view', id=id))

    form = ReceiptForm(obj=receipt)

    # Populate dropdowns
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    cash_bank_accounts = Account.query.filter(
        Account.account_type.in_(['Asset']),
        Account.name.like('%Cash%') | Account.name.like('%Bank%')
    ).order_by(Account.code).all()

    form.customer_id.choices = [(c.id, f'{c.code} - {c.name}') for c in customers]
    form.vendor_id.choices = [(v.id, f'{v.code} - {v.name}') for v in vendors]
    form.account_id.choices = [(a.id, f'{a.code} - {a.name}') for a in cash_bank_accounts]

    if form.validate_on_submit():
        try:
            old_values = model_to_dict(receipt, ['receipt_number', 'receipt_date', 'transaction_type', 'payment_method', 'amount', 'status'])

            receipt.receipt_number = form.receipt_number.data
            receipt.receipt_date = form.receipt_date.data
            receipt.payment_method = form.payment_method.data
            receipt.check_number = form.check_number.data if form.payment_method.data == 'check' else None
            receipt.check_date = form.check_date.data if form.payment_method.data == 'check' else None
            receipt.check_bank = form.check_bank.data if form.payment_method.data == 'check' else None
            receipt.bank_account = form.bank_account.data
            receipt.account_id = form.account_id.data if form.account_id.data else None
            receipt.amount = form.amount.data
            receipt.reference = form.reference.data
            receipt.notes = form.notes.data

            db.session.commit()

            new_values = model_to_dict(receipt, ['receipt_number', 'receipt_date', 'transaction_type', 'payment_method', 'amount', 'status'])
            log_update(
                module='receipt',
                record_id=receipt.id,
                record_identifier=f'{receipt.receipt_number} - {receipt.customer_name or receipt.vendor_name}',
                old_values=old_values,
                new_values=new_values
            )

            flash(f'{"Receipt" if receipt.transaction_type == "collection" else "Payment"} updated successfully!', 'success')
            return redirect(url_for('receipts.view', id=receipt.id))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating receipt/payment", exc_info=True)
            log_exception(e, severity='ERROR', module='receipts.update')
            db.session.rollback()
            flash(f'Error updating receipt/payment: {str(e)}', 'error')

    if request.method == 'GET':
        form.customer_id.data = receipt.customer_id
        form.vendor_id.data = receipt.vendor_id

    return render_template('receipts/form.html', form=form, receipt=receipt)


@receipts_bp.route('/receipts/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post(id):
    """Post receipt/payment (makes it final)."""
    receipt = Receipt.query.get_or_404(id)

    if receipt.status != 'draft':
        flash('Only draft receipts/payments can be posted.', 'error')
        return redirect(url_for('receipts.view', id=id))

    try:
        receipt.status = 'posted'
        receipt.posted_by_id = current_user.id
        receipt.posted_at = ph_now()
        db.session.commit()

        log_audit(
            module='receipt',
            action='post',
            record_id=receipt.id,
            record_identifier=f'{receipt.receipt_number} - {receipt.customer_name or receipt.vendor_name}',
            notes=f'{"Receipt" if receipt.transaction_type == "collection" else "Payment"} posted by {current_user.username}'
        )

        flash(f'{"Receipt" if receipt.transaction_type == "collection" else "Payment"} posted successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error posting receipt/payment", exc_info=True)
        log_exception(e, severity='ERROR', module='receipts.post')
        db.session.rollback()
        flash(f'Error posting: {str(e)}', 'error')

    return redirect(url_for('receipts.view', id=id))


@receipts_bp.route('/receipts/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    """Cancel receipt/payment."""
    receipt = Receipt.query.get_or_404(id)

    if receipt.status == 'cancelled':
        flash('Receipt/payment is already cancelled.', 'error')
        return redirect(url_for('receipts.view', id=id))

    try:
        receipt.status = 'cancelled'
        receipt.cancelled_at = ph_now()
        db.session.commit()

        log_audit(
            module='receipt',
            action='cancel',
            record_id=receipt.id,
            record_identifier=f'{receipt.receipt_number} - {receipt.customer_name or receipt.vendor_name}',
            notes=f'{"Receipt" if receipt.transaction_type == "collection" else "Payment"} cancelled by {current_user.username}'
        )

        flash(f'{"Receipt" if receipt.transaction_type == "collection" else "Payment"} cancelled.', 'warning')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error cancelling receipt/payment", exc_info=True)
        log_exception(e, severity='ERROR', module='receipts.cancel')
        db.session.rollback()
        flash(f'Error cancelling: {str(e)}', 'error')

    return redirect(url_for('receipts.view', id=id))


@receipts_bp.route('/receipts/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete receipt/payment (only drafts can be deleted)."""
    receipt = Receipt.query.get_or_404(id)

    if receipt.status != 'draft':
        flash('Only draft receipts/payments can be deleted.', 'error')
        return redirect(url_for('receipts.view', id=id))

    try:
        old_values = model_to_dict(receipt, ['receipt_number', 'receipt_date', 'transaction_type', 'amount', 'status'])
        receipt_number = receipt.receipt_number

        db.session.delete(receipt)
        db.session.commit()

        log_delete(
            module='receipt',
            record_id=id,
            record_identifier=f'{receipt_number}',
            old_values=old_values
        )

        flash(f'{"Receipt" if receipt.transaction_type == "collection" else "Payment"} "{receipt_number}" deleted successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error deleting receipt/payment", exc_info=True)
        log_exception(e, severity='ERROR', module='receipts.delete')
        db.session.rollback()
        flash(f'Error deleting: {str(e)}', 'error')

    return redirect(url_for('receipts.list_receipts'))
