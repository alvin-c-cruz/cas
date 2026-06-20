"""
Customer management views (Admin and Accountant only)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.customers.models import Customer
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax
from app.customers.forms import CustomerForm
from app.audit.utils import log_create, log_update, log_delete, model_to_dict
from app.utils.export import export_to_excel, export_to_csv
from app.utils import ph_now
from app.utils.wt_labels import wt_label

customers_bp = Blueprint('customers', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role for customer management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can manage customers.', 'error')
            return redirect(url_for('dashboard.home'))
        return f(*args, **kwargs)
    return decorated_function


# Single source of truth for the fields snapshotted to the audit trail and exported.
# Adding a Customer column means editing this one list, not 6 scattered literals.
CUSTOMER_FIELDS = ['code', 'name', 'contact_person', 'phone', 'email', 'tin',
                   'payment_terms', 'address', 'postal_code', 'default_vat_category',
                   'default_wt_code', 'is_active']

CUSTOMER_EXPORT_HEADERS = ['Customer Code', 'Customer Name', 'Contact Person', 'Phone',
                           'Email', 'TIN', 'Payment Terms', 'Address', 'Postal Code',
                           'VAT Category', 'WT Code', 'Active']


def _customer_export_rows(customers):
    """Build the export row dicts shared by the Excel and CSV export routes."""
    return [{
        'code': c.code,
        'name': c.name,
        'contact_person': c.contact_person or '',
        'phone': c.phone or '',
        'email': c.email or '',
        'tin': c.tin or '',
        'payment_terms': c.payment_terms or '',
        'address': c.address or '',
        'postal_code': c.postal_code or '',
        'default_vat_category': c.default_vat_category or '',
        'default_wt_code': c.default_wt_code or '',
        'is_active': 'Yes' if c.is_active else 'No',
    } for c in customers]


@customers_bp.route('/customers')
@login_required
def list_customers():
    """List customers with optional server-side search and pagination."""
    q = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int)
    query = Customer.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Customer.code.ilike(like),
            Customer.name.ilike(like),
            Customer.tin.ilike(like),
        ))
    pagination = query.order_by(Customer.code).paginate(
        page=page, per_page=25, error_out=False)
    return render_template('customers/list.html', customers=pagination.items,
                           pagination=pagination, search_query=q)


def generate_next_customer_code():
    """Generate the next customer code in sequence (C001, C002, ...).

    Sequences by the numeric suffix, not a lexicographic order_by(code.desc()):
    a string sort ranks 'C999' above 'C1000' and would re-propose an existing
    code once the count passes 999.
    """
    codes = [c.code for c in Customer.query.filter(Customer.code.like('C%')).all()]
    max_number = 0
    for code in codes:
        try:
            max_number = max(max_number, int(code[1:]))
        except (ValueError, IndexError):
            continue
    return f'C{max_number + 1:03d}'


def populate_dropdown_choices(form):
    """Populate VAT and WT dropdown choices from database"""
    # VAT Categories
    vat_categories = SalesVATCategory.query.filter_by(is_active=True).order_by(SalesVATCategory.name).all()
    vat_choices = [('', '-- Select --')]
    vat_choices.extend([(cat.name, cat.name) for cat in vat_categories])
    form.default_vat_category.choices = vat_choices

    # Withholding Tax
    wt_codes = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()
    wt_choices = [('', '-- Select --')]
    wt_choices.extend([(wt.code, f'{wt_label(wt.to_dict(), "sales")} ({wt.rate}%)') for wt in wt_codes])
    form.default_wt_code.choices = wt_choices


@customers_bp.route('/customers/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new customer"""
    form = CustomerForm()
    populate_dropdown_choices(form)

    if form.validate_on_submit():
        existing = Customer.query.filter_by(code=form.code.data).first()
        if existing:
            flash(f'Customer code "{form.code.data}" already exists.', 'error')
            return render_template('customers/form.html', form=form, customer=None)

        try:
            customer = Customer(
                code=form.code.data,
                name=form.name.data,
                contact_person=form.contact_person.data,
                phone=form.phone.data,
                email=form.email.data,
                tin=form.tin.data,
                payment_terms=form.payment_terms.data,
                address=form.address.data,
                postal_code=form.postal_code.data,
                default_vat_category=form.default_vat_category.data if form.default_vat_category.data else None,
                default_wt_code=form.default_wt_code.data if form.default_wt_code.data else None,
                is_active=bool(int(form.is_active.data)) if form.is_active.data else True,
                created_by_id=current_user.id,
                updated_by_id=current_user.id
            )
            db.session.add(customer)
            db.session.commit()

            # Audit log
            log_create(
                module='customer',
                record_id=customer.id,
                record_identifier=f'{customer.code} - {customer.name}',
                new_values=model_to_dict(customer, CUSTOMER_FIELDS)
            )

            flash(f'Customer "{customer.name}" created successfully!', 'success')
            return redirect(url_for('customers.list_customers'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating customer", exc_info=True, extra={
                'form_data': request.form.to_dict()
            })
            log_exception(e, severity='ERROR', module='customers.create')
            db.session.rollback()
            flash('An error occurred while creating the customer. Please try again.', 'error')

    if request.method == 'GET':
        form.code.data = generate_next_customer_code()
        form.is_active.data = '1'
        form.payment_terms.data = 'Net 30'

    return render_template('customers/form.html', form=form, customer=None)


@customers_bp.route('/customers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit(id):
    """Edit customer"""
    customer = Customer.query.get_or_404(id)
    form = CustomerForm(obj=customer)
    populate_dropdown_choices(form)

    if form.validate_on_submit():
        existing = Customer.query.filter(Customer.code == form.code.data, Customer.id != id).first()
        if existing:
            flash(f'Customer code "{form.code.data}" already exists.', 'error')
            return render_template('customers/form.html', form=form, customer=customer)

        try:
            # Capture old values before update
            old_values = model_to_dict(customer, CUSTOMER_FIELDS)

            customer.code = form.code.data
            customer.name = form.name.data
            customer.contact_person = form.contact_person.data
            customer.phone = form.phone.data
            customer.email = form.email.data
            customer.tin = form.tin.data
            customer.payment_terms = form.payment_terms.data
            customer.address = form.address.data
            customer.postal_code = form.postal_code.data
            customer.default_vat_category = form.default_vat_category.data if form.default_vat_category.data else None
            customer.default_wt_code = form.default_wt_code.data if form.default_wt_code.data else None
            customer.is_active = bool(int(form.is_active.data))
            customer.updated_by_id = current_user.id
            db.session.commit()

            # Audit log
            new_values = model_to_dict(customer, CUSTOMER_FIELDS)
            log_update(
                module='customer',
                record_id=customer.id,
                record_identifier=f'{customer.code} - {customer.name}',
                old_values=old_values,
                new_values=new_values
            )

            flash(f'Customer "{customer.name}" updated successfully!', 'success')
            return redirect(url_for('customers.list_customers'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating customer", exc_info=True)
            log_exception(e, severity='ERROR', module='customers.update')
            db.session.rollback()
            flash('An error occurred while updating the customer. Please try again.', 'error')

    if request.method == 'GET':
        form.code.data = customer.code
        form.name.data = customer.name
        form.contact_person.data = customer.contact_person
        form.phone.data = customer.phone
        form.email.data = customer.email
        form.tin.data = customer.tin
        form.payment_terms.data = customer.payment_terms
        form.address.data = customer.address
        form.postal_code.data = customer.postal_code
        form.default_vat_category.data = customer.default_vat_category
        form.default_wt_code.data = customer.default_wt_code
        form.is_active.data = '1' if customer.is_active else '0'

    return render_template('customers/form.html', form=form, customer=customer)


@customers_bp.route('/customers/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete customer"""
    customer = Customer.query.get_or_404(id)

    # Block deletion when the customer is still referenced by transactions.
    # SQLite does not enforce FK constraints by default, so the only thing
    # standing between a delete and an orphaned/ rejected row is this check
    # plus the child's NOT NULL column — make the guard explicit and the
    # message clear rather than relying on an IntegrityError fallback.
    from app.sales_invoices.models import SalesInvoice
    from app.cash_receipts.models import CashReceiptVoucher
    si_count = SalesInvoice.query.filter_by(customer_id=customer.id).count()
    cr_count = CashReceiptVoucher.query.filter_by(customer_id=customer.id).count()
    if si_count or cr_count:
        parts = []
        if si_count:
            parts.append(f'{si_count} sales invoice(s)')
        if cr_count:
            parts.append(f'{cr_count} cash receipt(s)')
        flash(f'Cannot delete customer "{customer.name}": it is referenced by '
              f'{" and ".join(parts)}. Set it inactive instead.', 'error')
        return redirect(url_for('customers.list_customers'))

    try:
        # Capture values before delete
        old_values = model_to_dict(customer, CUSTOMER_FIELDS)
        customer_identifier = f'{customer.code} - {customer.name}'
        customer_id = customer.id

        db.session.delete(customer)
        db.session.commit()

        # Audit log
        log_delete(
            module='customer',
            record_id=customer_id,
            record_identifier=customer_identifier,
            old_values=old_values
        )
        flash(f'Customer "{customer.name}" deleted successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error deleting customer", exc_info=True)
        log_exception(e, severity='ERROR', module='customers.delete')
        db.session.rollback()
        flash('An error occurred while deleting the customer. Please try again.', 'error')

    return redirect(url_for('customers.list_customers'))


@customers_bp.route('/customers/export/excel')
@login_required
@accountant_or_admin_required
def export_excel():
    """Export customers to Excel"""
    customers = Customer.query.order_by(Customer.code).all()
    data = _customer_export_rows(customers)
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')

    return export_to_excel(
        data=data,
        columns=CUSTOMER_FIELDS,
        headers=CUSTOMER_EXPORT_HEADERS,
        filename=f'customers_{timestamp}.xlsx',
        title='Customer List'
    )


@customers_bp.route('/customers/export/csv')
@login_required
@accountant_or_admin_required
def export_csv_route():
    """Export customers to CSV"""
    customers = Customer.query.order_by(Customer.code).all()
    data = _customer_export_rows(customers)
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')

    return export_to_csv(
        data=data,
        columns=CUSTOMER_FIELDS,
        headers=CUSTOMER_EXPORT_HEADERS,
        filename=f'customers_{timestamp}.csv'
    )
