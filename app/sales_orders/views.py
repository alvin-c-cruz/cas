"""Sales Orders views — create/edit/list/view.

Operational module only: posts NO journal entry, has NO GL account, NO WHT, NO payment.
Mirrors sales_invoices.views create/edit with all accounting stripped.
"""
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, current_app, jsonify)
from flask_login import login_required, current_user

from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.forms import SalesOrderForm
from app.customers.models import Customer
from app.customers.views import build_customer_quick_add_form
from app.withholding_tax.models import WithholdingTax
from app.users.models import User
from app.settings import AppSettings
from app.audit.utils import log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.cache_helpers import get_active_units, get_active_products, get_sales_vat_categories
from app.utils.concurrency import claim_version, conflict_message, submitted_version
from app.sales_orders.preprinted_layout import (
    get_layout, save_layout, FONT_GROUPS, COLUMN_LABELS, PAPER_SIZES, PAPER_LABELS,
    DATE_FORMATS, FIELD_LABELS, TEXT_KEYS)

sales_orders_bp = Blueprint('sales_orders', __name__, template_folder='templates')

VALID_SO_STATUSES = {'draft', 'confirmed', 'cancelled', 'closed'}


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
    kept = 0
    for idx, d in enumerate(items, start=1):
        vat_rate = _dec(d.get('vat_rate')) or Decimal('0.00')
        product_id = _int(d.get('product_id'))
        amount = Decimal(str(d.get('amount', '0') or '0'))
        qty = _dec(d.get('quantity'))
        price = _dec(d.get('unit_price'))
        is_empty = (product_id is None and (amount is None or amount == 0)
                    and qty is None and price is None)
        if is_empty:
            continue  # skip a blank trailing line
        if product_id is None:
            raise ValueError(f'Line {idx}: select a product.')
        kept += 1
        li = SalesOrderItem(
            line_number=kept,
            quantity=qty,
            unit_price=price,
            uom_text=(d.get('uom_text') or None),
            unit_of_measure_id=_int(d.get('uom_id')),
            product_id=product_id,
            amount=amount,
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
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('sales_orders.list'))
    return None


# ── form context helper ───────────────────────────────────────────────────────

def _salesperson_choices(branch_id):
    """(0,'-- None --') + active, branch-scoped employees — only when the Employees module is on."""
    from app.users.module_access import module_enabled
    from app.employees.models import Employee
    choices = [(0, 'Company Account')]   # null salesperson = house/company account
    if module_enabled('employees') and branch_id:
        emps = (Employee.query.filter_by(is_active=True, is_salesperson=True, branch_id=branch_id)
                .order_by(Employee.last_name, Employee.first_name).all())
        choices += [(e.id, f'{e.employee_no} - {e.full_name}') for e in emps]
    return choices


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

@sales_orders_bp.route('/sales-orders/monitor')
@login_required
def monitor():
    """Read-only, count-based Order Monitoring dashboard (branch-scoped)."""
    branch_id = session.get('selected_branch_id')
    if not branch_id:
        flash('Please select a branch first.', 'error')
        return redirect(url_for('users.select_branch', next=request.url))
    from app.sales_orders.monitoring import get_order_monitoring
    metrics = get_order_monitoring(branch_id, ph_now().date())
    return render_template('sales_orders/monitoring.html', **metrics)


@sales_orders_bp.route('/sales-orders')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    page = request.args.get('page', 1, type=int)

    query = SalesOrder.query.filter_by(branch_id=branch_id)

    # Status filter
    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_SO_STATUSES:
        query = query.filter_by(status=status_filter)

    # Drill-through filters from Order Monitoring (applied only when present)
    _today = ph_now().date()
    if request.args.get('overdue') == '1':
        query = query.filter(SalesOrder.status == 'confirmed',
                             SalesOrder.expected_delivery_date.isnot(None),
                             SalesOrder.expected_delivery_date < _today)
    if request.args.get('due_soon') == '1':
        query = query.filter(SalesOrder.status == 'confirmed',
                             SalesOrder.expected_delivery_date.isnot(None),
                             SalesOrder.expected_delivery_date >= _today,
                             SalesOrder.expected_delivery_date <= _today + timedelta(days=7))

    # Customer filter
    customer_filter = request.args.get('customer_id', 'all')
    if customer_filter != 'all':
        try:
            query = query.filter_by(customer_id=int(customer_filter))
        except ValueError:
            pass

    # Text search
    q_text = request.args.get('q', '').strip()
    if q_text:
        like = f'%{q_text}%'
        query = query.filter(
            db.or_(SalesOrder.so_number.ilike(like),
                   SalesOrder.customer_name.ilike(like))
        )

    # Date range
    year = ph_now().year
    date_from = request.args.get('date_from', f'{year}-01-01')
    if date_from:
        try:
            query = query.filter(SalesOrder.order_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', f'{year}-12-31')
    if date_to:
        try:
            query = query.filter(SalesOrder.order_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    query = query.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    return render_template('sales_orders/list.html',
                           orders=pagination.items,
                           pagination=pagination,
                           customers=customers,
                           status_filter=status_filter,
                           customer_filter=customer_filter,
                           q=q_text,
                           date_from=date_from,
                           date_to=date_to)


@sales_orders_bp.route('/sales-orders/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _role_gate()
    if gate:
        return gate

    form = SalesOrderForm()
    form.salesperson_id.choices = _salesperson_choices(session.get('selected_branch_id'))

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
                salesperson_id=(form.salesperson_id.data or None),
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

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('sales_orders/form.html', form=form, so=None,
                                   line_items=[], **_common_form_ctx())
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
    form.salesperson_id.choices = _salesperson_choices(session.get('selected_branch_id'))

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

            # Lost-update guard: the first write, before the line teardown below.
            if not claim_version(SalesOrder, so.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('sales_orders', so.id), 'error')
                return render_template('sales_orders/form.html', form=form, so=so,
                                       line_items=restore_items, **_common_form_ctx())

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
            so.salesperson_id = form.salesperson_id.data or None
            so.notes = form.notes.data or ''

            db.session.execute(db.delete(SalesOrderItem).where(SalesOrderItem.sales_order_id == so.id))
            _parse_and_attach_so_lines(so, request.form.get('line_items', '[]'))
            db.session.flush()
            db.session.expire(so, ['line_items'])
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

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('sales_orders/form.html', form=form, so=so,
                                   line_items=restore_items, **_common_form_ctx())
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
    """Read-only detail view for a Sales Order."""
    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)
    created_by_user = (db.session.get(User, so.created_by_id)
                       if so.created_by_id else None)
    confirmed_by_user = (db.session.get(User, so.confirmed_by_id)
                         if so.confirmed_by_id else None)
    cancelled_by_user = (db.session.get(User, so.cancelled_by_id)
                         if so.cancelled_by_id else None)
    return render_template('sales_orders/detail.html', so=so,
                           created_by_user=created_by_user,
                           confirmed_by_user=confirmed_by_user,
                           cancelled_by_user=cancelled_by_user)


@sales_orders_bp.route('/sales-orders/<int:id>/print')
@login_required
def print_so(id):
    """Print a Sales Order — the form is chosen by the `so_print_form` company setting
    (current = standard printable form · preprinted = data-only overlay for BIR-registered
    physical stock · hidden = printing disabled). Mirrors the SI/APV/CRV/CDV pattern."""
    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)
    so_print_form = AppSettings.get_setting('so_print_form', 'current')
    if so_print_form == 'hidden':
        flash('Sales Order printing is not enabled.', 'error')
        return redirect(url_for('sales_orders.view', id=id))
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    if so_print_form == 'preprinted':
        return render_template(
            'sales_orders/print_preprinted.html', so=so, company=company,
            printed_at=ph_now(), layout=get_layout(so.branch_id),
            can_edit_layout=current_user.has_full_access,
            col_labels=COLUMN_LABELS, font_groups=FONT_GROUPS,
            paper_sizes=PAPER_SIZES, paper_labels=PAPER_LABELS,
            date_formats=DATE_FORMATS, field_labels=FIELD_LABELS,
            signatory_ids=TEXT_KEYS,
            date_labels={k: date(2026, 6, 17).strftime(v) for k, v in DATE_FORMATS.items()})
    return render_template('sales_orders/print.html', so=so,
                           company=company, printed_at=ph_now())


@sales_orders_bp.route('/sales-orders/<int:id>/print-job-order')
@login_required
def print_job_order(id):
    """Operations-facing Job Order Slip -- same SalesOrder record as print_so, no pricing,
    uses each line's Product.job_order_name (falling back to Product.name) instead of the
    name that prints on the DR/SI. Not gated by so_print_form -- that setting controls the
    accounting SO print form only."""
    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('sales_orders/print_job_order.html', so=so,
                           company=company, printed_at=ph_now())


@sales_orders_bp.route('/sales-orders/job-order-slips')
@login_required
def job_order_list():
    """Operations-facing list of Sales Orders for printing Job Order Slips -- no pricing
    columns. Draft-status SOs are hidden unless job_order_slips_show_drafts is on."""
    branch_id = session.get('selected_branch_id')
    query = SalesOrder.query.filter_by(branch_id=branch_id)
    if AppSettings.get_setting('job_order_slips_show_drafts', '0') != '1':
        query = query.filter(SalesOrder.status != 'draft')
    orders = query.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc()).all()
    return render_template('sales_orders/job_order_list.html', orders=orders)


@sales_orders_bp.route('/sales-orders/print-layout', methods=['POST'])
@login_required
def save_print_layout():
    """Persist the pre-printed layout JSON (full-access: admin or Chief Accountant)."""
    if not current_user.has_full_access:
        abort(403)
    data = request.get_json(silent=True) or {}
    # The layout is per-branch; the print page requires the selected branch to equal
    # the document's branch, so the session branch is the document's branch.
    clean = save_layout(data, current_user.username, session.get('selected_branch_id'))
    return jsonify(ok=True, layout=clean)


# ── confirm / cancel ──────────────────────────────────────────────────────────

@sales_orders_bp.route('/sales-orders/<int:id>/confirm', methods=['POST'])
@login_required
def confirm(id):
    """Draft → confirmed.  No journal entry — SO posts nothing."""
    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)

    # Role guard: staff/accountant/admin (mirrors detail.html gating)
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to confirm Sales Orders.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    if so.status != 'draft':
        flash('Only draft Sales Orders can be confirmed.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    if so.customer and so.customer.po_required and not (so.customer_po_number or '').strip():
        flash(f'Customer "{so.customer_name}" requires a Purchase Order number before this '
              f'Sales Order can be confirmed.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    old_values = model_to_dict(so, ['status'])
    so.status = 'confirmed'
    so.confirmed_by_id = current_user.id
    so.confirmed_at = ph_now()
    db.session.commit()

    log_update(
        module='sales_orders',
        record_id=so.id,
        record_identifier=so.so_number,
        old_values=old_values,
        new_values=model_to_dict(so, ['status']),
        notes='Confirmed',
    )

    flash(f'Sales Order "{so.so_number}" has been confirmed.', 'success')
    return redirect(url_for('sales_orders.view', id=id))


@sales_orders_bp.route('/sales-orders/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    """Non-terminal SO → cancelled.  Captures a reason from the custom modal form."""
    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)

    # Role guard: accountant/admin (mirrors detail.html gating)
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to cancel Sales Orders.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    # Terminal-status guard
    if so.status in ('cancelled', 'closed'):
        flash('This Sales Order has already been cancelled or closed.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    # P-60 billed guard: do not cancel an SO that has been invoiced
    if so.sales_invoice_id is not None:
        flash('A billed Sales Order cannot be cancelled. Void the invoice first.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Please provide a cancellation reason (at least 10 characters).', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    old_values = model_to_dict(so, ['status'])
    so.status = 'cancelled'
    so.cancelled_by_id = current_user.id
    so.cancelled_at = ph_now()
    so.cancel_reason = cancel_reason
    db.session.commit()

    log_update(
        module='sales_orders',
        record_id=so.id,
        record_identifier=so.so_number,
        old_values=old_values,
        new_values=model_to_dict(so, ['status']),
        notes=f'Cancelled: {cancel_reason}',
    )

    flash(f'Sales Order "{so.so_number}" has been cancelled.', 'success')
    return redirect(url_for('sales_orders.view', id=id))
