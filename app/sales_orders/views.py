"""Sales Orders views — create/edit/list/view.

Operational module only: posts NO journal entry, has NO GL account, NO WHT, NO payment.
Mirrors sales_invoices.views create/edit with all accounting stripped.
"""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, current_app)
from flask_login import login_required, current_user

from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.forms import SalesOrderForm
from app.customers.models import Customer
from app.customers.views import build_customer_quick_add_form
from app.withholding_tax.models import WithholdingTax
from app.audit.utils import log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.cache_helpers import get_active_units, get_active_products, get_sales_vat_categories

sales_orders_bp = Blueprint('sales_orders', __name__, template_folder='templates')


# ── line-item helpers (kept from Tasks 1-3) ──────────────────────────────────

def _parse_and_attach_so_lines(so, lines_json):
    """Parse hidden-JSON line array and attach SalesOrderItem objects to *so*.
    Mirrors sales_invoices.views._parse_and_attach_line_items but with no account_id/wt.
    """
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

    items = json.loads(lines_json) if lines_json else []
    for idx, d in enumerate(items, start=1):
        vat_rate = _dec(d.get('vat_rate')) or Decimal('0.00')
        li = SalesOrderItem(
            line_number=idx,
            description=d.get('description', ''),
            quantity=_dec(d.get('quantity')),
            unit_price=_dec(d.get('unit_price')),
            uom_text=(d.get('uom_text') or None),
            unit_of_measure_id=_int(d.get('uom_id')),
            product_id=_int(d.get('product_id')),
            amount=Decimal(str(d.get('amount', '0') or '0')),
            vat_category=d.get('vat_category') or None,
            vat_rate=vat_rate,
        )
        li.calculate_amounts()
        so.line_items.append(li)


def generate_so_number():
    """Next SO-YYYY-MM-#### for the current PH month (suffix = max existing this month + 1)."""
    today = ph_now().date()
    prefix = f"SO-{today.year:04d}-{today.month:02d}-"
    rows = (SalesOrder.query
            .filter(SalesOrder.so_number.like(prefix + '%'))
            .with_entities(SalesOrder.so_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"


# ── role gate ────────────────────────────────────────────────────────────────

def _role_gate():
    """Returns a redirect if the current user may not write SOs, else None."""
    if current_user.role not in ['staff', 'accountant', 'admin']:
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('sales_orders.list'))
    return None


# ── form context helper ───────────────────────────────────────────────────────

def _common_form_ctx():
    """Build the common template context shared by create and edit."""
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    return {
        'units': [u.to_dict() for u in get_active_units()],
        'products': [p.to_dict() for p in get_active_products()],
        'vat_categories': [v.to_dict() for v in get_sales_vat_categories()],
        'customers': customers,
        'customer_quick_add_form': build_customer_quick_add_form(),
        'customer_quick_add_whts': WithholdingTax.query.filter_by(is_active=True)
                                   .order_by(WithholdingTax.code).all(),
    }


# ── routes ───────────────────────────────────────────────────────────────────

@sales_orders_bp.route('/sales-orders')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    page = request.args.get('page', 1, type=int)
    q = (SalesOrder.query
         .filter_by(branch_id=branch_id)
         .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc()))
    pagination = q.paginate(page=page, per_page=50, error_out=False)
    return render_template('sales_orders/list.html',
                           orders=pagination.items,
                           pagination=pagination)


@sales_orders_bp.route('/sales-orders/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _role_gate()
    if gate:
        return gate

    form = SalesOrderForm()

    if form.validate_on_submit():
        so_number = (form.so_number.data or '').strip()
        if not so_number:
            flash('SO number is required.', 'error')
            return render_template('sales_orders/form.html', form=form, so=None,
                                   line_items=[], **_common_form_ctx())

        # Uniqueness check (no self-exclusion for create)
        if SalesOrder.query.filter(SalesOrder.so_number == so_number).first():
            flash('Sales Order number already exists.', 'error')
            return render_template('sales_orders/form.html', form=form, so=None,
                                   line_items=[], **_common_form_ctx())

        try:
            customer_id = int(form.customer_id.data)
        except (ValueError, TypeError):
            flash('Invalid customer.', 'error')
            return render_template('sales_orders/form.html', form=form, so=None,
                                   line_items=[], **_common_form_ctx())

        cust = db.session.get(Customer, customer_id)
        if not cust:
            flash('Selected customer not found.', 'error')
            return render_template('sales_orders/form.html', form=form, so=None,
                                   line_items=[], **_common_form_ctx())

        try:
            so = SalesOrder(
                branch_id=session.get('selected_branch_id'),
                so_number=so_number,
                order_date=form.order_date.data,
                expected_delivery_date=form.expected_delivery_date.data or None,
                customer_id=cust.id,
                customer_name=cust.name,
                customer_tin=cust.tin,
                customer_address=cust.address,
                customer_po_number=form.customer_po_number.data or None,
                customer_po_date=form.customer_po_date.data or None,
                payment_terms=form.payment_terms.data,
                reference=form.reference.data or None,
                notes=form.notes.data or '',
                status='draft',
                created_by_id=current_user.id,
            )
            _parse_and_attach_so_lines(so, request.form.get('line_items', '[]'))
            so.calculate_totals()
            db.session.add(so)
            db.session.commit()

            log_create(
                module='sales_orders',
                record_id=so.id,
                record_identifier=f'{so.so_number} - {so.customer_name}',
                new_values=model_to_dict(so, [
                    'so_number', 'order_date', 'customer_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status'])
            )
            flash(f'Sales Order "{so.so_number}" created successfully!', 'success')
            return redirect(url_for('sales_orders.list'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating sales order', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_orders.create')
            flash('An error occurred while entering the Sales Order. Please try again.', 'error')

    if request.method == 'GET':
        form.so_number.data = generate_so_number()
        form.order_date.data = ph_now().date()

    return render_template('sales_orders/form.html', form=form, so=None,
                           line_items=[], **_common_form_ctx())


@sales_orders_bp.route('/sales-orders/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _role_gate()
    if gate:
        return gate

    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)
    if so.status != 'draft':
        flash('Only draft Sales Orders can be edited.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    form = SalesOrderForm(obj=so)

    restore_items = ([item.to_dict() for item in so.line_items]
                     if request.method == 'GET'
                     else json.loads(request.form.get('line_items', '[]') or '[]'))

    if form.validate_on_submit():
        so_number = (form.so_number.data or '').strip()

        # Uniqueness — exclude self
        duplicate = SalesOrder.query.filter(
            SalesOrder.so_number == so_number,
            SalesOrder.id != so.id
        ).first()
        if duplicate:
            flash('Sales Order number already exists.', 'error')
            return render_template('sales_orders/form.html', form=form, so=so,
                                   line_items=restore_items, **_common_form_ctx())

        try:
            customer_id = int(form.customer_id.data)
        except (ValueError, TypeError):
            flash('Invalid customer.', 'error')
            return render_template('sales_orders/form.html', form=form, so=so,
                                   line_items=restore_items, **_common_form_ctx())

        cust = db.session.get(Customer, customer_id)
        if not cust:
            flash('Selected customer not found.', 'error')
            return render_template('sales_orders/form.html', form=form, so=so,
                                   line_items=restore_items, **_common_form_ctx())

        try:
            old_values = model_to_dict(so, [
                'so_number', 'order_date', 'customer_name',
                'subtotal', 'vat_amount', 'total_amount', 'status'])

            so.so_number = so_number
            so.order_date = form.order_date.data
            so.expected_delivery_date = form.expected_delivery_date.data or None
            so.customer_id = cust.id
            so.customer_name = cust.name
            so.customer_tin = cust.tin
            so.customer_address = cust.address
            so.customer_po_number = form.customer_po_number.data or None
            so.customer_po_date = form.customer_po_date.data or None
            so.payment_terms = form.payment_terms.data
            so.reference = form.reference.data or None
            so.notes = form.notes.data or ''

            SalesOrderItem.query.filter_by(sales_order_id=so.id).delete()
            _parse_and_attach_so_lines(so, request.form.get('line_items', '[]'))
            db.session.flush()
            so.calculate_totals()
            db.session.commit()

            log_update(
                module='sales_orders',
                record_id=so.id,
                record_identifier=f'{so.so_number} - {so.customer_name}',
                old_values=old_values,
                new_values=model_to_dict(so, [
                    'so_number', 'order_date', 'customer_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status'])
            )
            flash(f'Sales Order "{so.so_number}" updated successfully!', 'success')
            return redirect(url_for('sales_orders.view', id=so.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error updating sales order', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_orders.edit')
            flash('An error occurred while saving the Sales Order. Please try again.', 'error')

    return render_template('sales_orders/form.html', form=form, so=so,
                           line_items=restore_items, **_common_form_ctx())


@sales_orders_bp.route('/sales-orders/<int:id>')
@login_required
def view(id):
    """View stub — detail template will be built in Task 6."""
    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)
    return render_template('sales_orders/view.html', so=so)


# ── confirm / cancel stubs (Task 8) ──────────────────────────────────────────

@sales_orders_bp.route('/sales-orders/<int:id>/confirm', methods=['POST'])
@login_required
def confirm(id):
    """Stub — wired in Task 8."""
    flash('Confirm not yet implemented.', 'warning')
    return redirect(url_for('sales_orders.view', id=id))


@sales_orders_bp.route('/sales-orders/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    """Stub — wired in Task 8."""
    flash('Cancel not yet implemented.', 'warning')
    return redirect(url_for('sales_orders.view', id=id))
