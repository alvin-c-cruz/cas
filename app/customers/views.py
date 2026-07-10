"""
Customer management views (Admin and Accountant only)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy import func
from app import db
from app.customers.models import Customer
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax
from app.customers.forms import CustomerForm
from app.sales_invoices.models import SalesInvoice
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
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can manage customers.', 'error')
            return redirect(url_for('dashboard.home'))
        return f(*args, **kwargs)
    return decorated_function


def staff_or_above_required(f):
    """Staff, accountant, and admin allowed (matches vendors; used by quick-add create)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.home'))
        return f(*args, **kwargs)
    return decorated_function


def _wants_json():
    """True when the request is an AJAX/JSON call (modal quick-add)."""
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )


def build_customer_quick_add_form():
    """A populated CustomerForm for the inline Add-Customer modal."""
    form = CustomerForm()
    populate_dropdown_choices(form)
    form.code.data = generate_next_customer_code()
    form.is_active.data = '1'
    form.payment_terms.data = 'Net 30'
    return form


# Single source of truth for the fields snapshotted to the audit trail and exported.
# Adding a Customer column means editing this one list, not 6 scattered literals.
CUSTOMER_FIELDS = ['code', 'name', 'contact_person', 'phone', 'email', 'tin',
                   'payment_terms', 'address', 'postal_code', 'default_vat_category',
                   'default_wt_code', 'withholding_taxes_str', 'is_active']

CUSTOMER_EXPORT_HEADERS = ['Customer Code', 'Customer Name', 'Contact Person', 'Phone',
                           'Email', 'TIN', 'Payment Terms', 'Address', 'Postal Code',
                           'VAT Category', 'WT Code', 'WT Codes', 'Active']


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
        'withholding_taxes_str': ', '.join(w.code for w in c.withholding_taxes),
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


def _collections_by_invoice(invoice_ids):
    """Map each invoice id -> the posted CRVs that settled it, for the
    Collected-column popup. Returns {invoice_id: [{'number','date','amount'}, ...]}.
    Only posted CRVs count toward amount_paid; draft/voided are excluded.
    """
    if not invoice_ids:
        return {}
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
    rows = (
        CRVArLine.query
        .join(CashReceiptVoucher, CRVArLine.crv_id == CashReceiptVoucher.id)
        .filter(CRVArLine.invoice_id.in_(invoice_ids),
                CashReceiptVoucher.status == 'posted')
        .order_by(CashReceiptVoucher.crv_date, CashReceiptVoucher.crv_number)
        .all()
    )
    result = {}
    for line in rows:
        result.setdefault(line.invoice_id, []).append({
            'number': line.crv.crv_number,
            'date': line.crv.crv_date.strftime('%d %b %Y'),
            'amount': float(line.amount_applied),
        })
    return result


@customers_bp.route('/customers/<int:id>')
@login_required
def detail(id):
    """Customer detail: Overview (info + AR aging + creditable WHT YTD) and
    Invoices tabs. Read view — mirrors vendors.detail (no role gate, no audit)."""
    customer = db.get_or_404(Customer, id)
    tab = request.args.get('tab', 'overview')
    total_invoices = SalesInvoice.query.filter_by(customer_id=id).count()

    if tab == 'invoices':
        from datetime import date as date_type
        page = request.args.get('page', 1, type=int)
        date_from_str = request.args.get('date_from', '')
        date_to_str = request.args.get('date_to', '')
        status_filter = request.args.get('status', 'all')

        query = SalesInvoice.query.filter_by(customer_id=id)
        if date_from_str:
            try:
                query = query.filter(SalesInvoice.invoice_date >= date_type.fromisoformat(date_from_str))
            except ValueError:
                pass
        if date_to_str:
            try:
                query = query.filter(SalesInvoice.invoice_date <= date_type.fromisoformat(date_to_str))
            except ValueError:
                pass
        if status_filter and status_filter != 'all':
            query = query.filter(SalesInvoice.status == status_filter)

        pagination = query.order_by(SalesInvoice.invoice_date.desc()).paginate(
            page=page, per_page=20, error_out=False
        )
        collections = _collections_by_invoice([inv.id for inv in pagination.items])
        return render_template(
            'customers/detail.html',
            customer=customer,
            tab='invoices',
            total_invoices=total_invoices,
            pagination=pagination,
            collections=collections,
            date_from=date_from_str,
            date_to=date_to_str,
            status_filter=status_filter,
        )
    else:
        from app.customers.utils import compute_ar_aging, compute_creditable_wht_ytd
        aging = compute_ar_aging(customer.id)
        wht_ytd = compute_creditable_wht_ytd(customer.id)
        return render_template(
            'customers/detail.html',
            customer=customer,
            tab='overview',
            total_invoices=total_invoices,
            aging=aging,
            wht_ytd=wht_ytd,
        )


@customers_bp.route('/customers/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    """Create new customer"""
    form = CustomerForm()
    populate_dropdown_choices(form)

    if form.validate_on_submit():
        existing = Customer.query.filter_by(code=form.code.data).first()
        if existing:
            if _wants_json():
                return jsonify(ok=False,
                               errors={'code': f'Customer code "{form.code.data}" already exists.'}), 422
            flash(f'Customer code "{form.code.data}" already exists.', 'error')
            return render_template('customers/form.html', form=form, customer=None)

        # Check for duplicate customer name (case-insensitive, warn-but-allow)
        _dup_name = Customer.query.filter(
            func.lower(Customer.name) == form.name.data.strip().lower()
        ).first()

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
                po_required=bool(form.po_required.data),
                created_by_id=current_user.id,
                updated_by_id=current_user.id
            )

            # Handle many-to-many withholding taxes
            withholding_tax_ids = request.form.getlist('withholding_tax_ids')
            if withholding_tax_ids:
                selected_wts = WithholdingTax.query.filter(
                    WithholdingTax.id.in_(withholding_tax_ids)).all()
                customer.withholding_taxes = selected_wts

            db.session.add(customer)
            db.session.commit()

            # Audit log
            log_create(
                module='customer',
                record_id=customer.id,
                record_identifier=f'{customer.code} - {customer.name}',
                new_values=model_to_dict(customer, CUSTOMER_FIELDS)
            )

            if _wants_json():
                return jsonify(ok=True, customer={
                    'id': customer.id,
                    'label': f'{customer.code} - {customer.name}',
                })
            if _dup_name:
                flash(f"A customer named '{customer.name}' already exists.", 'warning')
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

    if request.method == 'POST' and _wants_json():
        return jsonify(ok=False,
                       errors={f: errs[0] for f, errs in form.errors.items()}), 422

    if request.method == 'GET':
        form.code.data = generate_next_customer_code()
        form.is_active.data = '1'
        form.payment_terms.data = 'Net 30'

    withholding_taxes = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()
    return render_template('customers/form.html', form=form, customer=None,
                           withholding_taxes=withholding_taxes)


@customers_bp.route('/customers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit(id):
    """Edit customer"""
    customer = db.get_or_404(Customer, id)
    form = CustomerForm(obj=customer)
    populate_dropdown_choices(form)

    if form.validate_on_submit():
        existing = Customer.query.filter(Customer.code == form.code.data, Customer.id != id).first()
        if existing:
            flash(f'Customer code "{form.code.data}" already exists.', 'error')
            return render_template('customers/form.html', form=form, customer=customer)

        # Check for duplicate customer name (case-insensitive, warn-but-allow, self-excluded)
        _dup_name = Customer.query.filter(
            func.lower(Customer.name) == form.name.data.strip().lower(),
            Customer.id != id
        ).first()

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
            # default_wt_code is legacy (the WHT multi-select is the source of truth now);
            # the form no longer exposes its picker, so preserve any existing value here.
            customer.is_active = bool(int(form.is_active.data))
            customer.po_required = bool(form.po_required.data)
            customer.updated_by_id = current_user.id

            # Handle many-to-many withholding taxes
            withholding_tax_ids = request.form.getlist('withholding_tax_ids')
            selected_wts = WithholdingTax.query.filter(
                WithholdingTax.id.in_(withholding_tax_ids)).all() if withholding_tax_ids else []
            customer.withholding_taxes = selected_wts

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

            if _dup_name:
                flash(f"A customer named '{customer.name}' already exists.", 'warning')
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

    withholding_taxes = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()
    selected_wt_ids = {wt.id for wt in customer.withholding_taxes}
    return render_template('customers/form.html', form=form, customer=customer,
                           withholding_taxes=withholding_taxes,
                           selected_wt_ids=selected_wt_ids)


@customers_bp.route('/customers/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete customer"""
    customer = db.get_or_404(Customer, id)

    # Block deletion when the customer is still referenced by transactions.
    # SQLite does not enforce FK constraints by default, so the only thing
    # standing between a delete and an orphaned/ rejected row is this check
    # plus the child's NOT NULL column — make the guard explicit and the
    # message clear rather than relying on an IntegrityError fallback.
    from app.sales_invoices.models import SalesInvoice
    from app.cash_receipts.models import CashReceiptVoucher
    from app.delivery_receipts.models import DeliveryReceipt
    from app.sales_memos.models import SalesMemo
    from app.quotations.models import Quotation
    from app.sales_orders.models import SalesOrder
    checks = [
        ('sales invoice(s)', SalesInvoice),
        ('cash receipt(s)', CashReceiptVoucher),
        ('sales order(s)', SalesOrder),
        ('delivery receipt(s)', DeliveryReceipt),
        ('quotation(s)', Quotation),
        ('memo(s)', SalesMemo),
    ]
    parts = []
    for label, model in checks:
        n = model.query.filter_by(customer_id=customer.id).count()
        if n:
            parts.append(f'{n} {label}')
    if parts:
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


@customers_bp.route('/customers/<int:id>/defaults')
@login_required
def customer_defaults(id):
    """Return a customer's default VAT category, WHT code, payment terms, and
    last-used revenue account for AJAX — mirrors `/vendors/<id>/defaults` so the
    Sales Invoice customer card can auto-fill line defaults like the APV vendor card.

    A customer has a single `default_wt_code` (vs a vendor's many-to-many), so it
    is emitted as a 0-or-1-item `withholding_taxes` list to keep the same response
    shape as the vendor endpoint.
    """
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem

    customer = db.get_or_404(Customer, id)

    withholding_taxes = [
        {'id': wt.id, 'code': wt.code, 'name': wt.sales_name or wt.name, 'rate': float(wt.rate)}
        for wt in customer.withholding_taxes if wt.is_active
    ]

    last_item = (
        SalesInvoiceItem.query
        .join(SalesInvoice)
        .filter(SalesInvoice.customer_id == id, SalesInvoice.status != 'voided')
        .order_by(SalesInvoice.created_at.desc(), SalesInvoiceItem.line_number.asc())
        .first()
    )

    # Cash-receipt defaults: the cash/bank account and direct-revenue account this
    # customer used on their most recent POSTED CRV — so the CRV form can pre-fill
    # both (defaults only; the user can still override).
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    last_crv = (
        CashReceiptVoucher.query
        .filter_by(customer_id=id, status='posted')
        .order_by(CashReceiptVoucher.crv_date.desc(), CashReceiptVoucher.id.desc())
        .first()
    )
    last_rev_line = (
        CRVRevenueLine.query
        .join(CashReceiptVoucher)
        .filter(CashReceiptVoucher.customer_id == id,
                CashReceiptVoucher.status == 'posted',
                CRVRevenueLine.account_id.isnot(None))
        .order_by(CashReceiptVoucher.crv_date.desc(), CashReceiptVoucher.id.desc(),
                  CRVRevenueLine.line_number.asc())
        .first()
    )

    return jsonify({
        'withholding_taxes': withholding_taxes,
        'default_vat_category': customer.default_vat_category,
        'payment_terms': customer.payment_terms or 'Net 30',
        'last_account_id': last_item.account_id if last_item else None,
        'last_cash_account_id': last_crv.cash_account_id if last_crv else None,
        'last_revenue_account_id': last_rev_line.account_id if last_rev_line else None,
    })
