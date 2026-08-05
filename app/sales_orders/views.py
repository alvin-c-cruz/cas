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
from app.branches.models import Branch
from app.sales_orders.forms import SalesOrderForm, SalesOrderAmendForm
from app.customers.models import Customer, CustomerDeliverySite
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
from app.sales_orders.revisions import write_revision, validate_amendment

sales_orders_bp = Blueprint('sales_orders', __name__, template_folder='templates')

VALID_SO_STATUSES = {'draft', 'confirmed', 'cancelled', 'closed'}


# ── line-item helpers (kept from Tasks 1-3) ──────────────────────────────────

def _so_line_dec(v):
    try:
        return Decimal(str(v)) if v not in (None, '', 'null') else None
    except (InvalidOperation, TypeError):
        return None


def _so_line_int(v):
    try:
        return int(v) if v and str(v).strip() not in ('', 'null') else None
    except (ValueError, TypeError):
        return None


def _so_line_date(v):
    if v in (None, '', 'null'):
        return None
    try:
        return date.fromisoformat(v)
    except (ValueError, TypeError):
        return None


def _so_line_delivery_site_id(so, v):
    """Resolve a submitted delivery_site_id, but only if it actually belongs to
    this SO's own customer -- a direct POST, a replay, or a stale in-memory line
    array (e.g. from before a header customer change) must never silently persist
    a foreign customer's site. Mirrors this parser's tolerant style for other
    optional cross-reference fields (invalid/missing -> None, not a raised error).
    """
    site_id = _so_line_int(v)
    if site_id is None:
        return None
    site = db.session.get(CustomerDeliverySite, site_id)
    if site is None or site.customer_id != so.customer_id:
        return None
    return site_id


def _assign_so_line_fields(so, item, d, idx):
    """Coerce + assign one submitted line's fields onto *item* (new or existing).

    Shared by both parsers below -- _parse_and_attach_so_lines (draft create/edit,
    rebuild-from-scratch) and _apply_amended_so_lines (post-confirm amend, update
    in place) -- so the coercion/validation rules (including the delivery-site
    ownership check) exist in exactly one place. Does NOT touch line_status,
    closed_by_id, closed_at, or closed_reason -- those are not form fields.

    *idx* is the line's 1-based position in the SUBMITTED array (including any
    blank trailing lines) and is used only in the raised ValueError's message --
    it mirrors the original inlined behaviour exactly. It is NOT the same
    number as item.line_number, which callers assign separately once they know
    how many non-blank lines have been kept so far.

    Returns False (and leaves *item* untouched) for a blank trailing line;
    True otherwise.
    """
    vat_rate = _so_line_dec(d.get('vat_rate')) or Decimal('0.00')
    product_id = _so_line_int(d.get('product_id'))
    amount = Decimal(str(d.get('amount', '0') or '0'))
    qty = _so_line_dec(d.get('quantity'))
    price = _so_line_dec(d.get('unit_price'))
    is_empty = (product_id is None and (amount is None or amount == 0)
                and qty is None and price is None)
    if is_empty:
        return False  # skip a blank trailing line
    if product_id is None:
        raise ValueError(f'Line {idx}: select a product.')

    item.quantity = qty
    item.unit_price = price
    item.uom_text = (d.get('uom_text') or None)
    item.unit_of_measure_id = _so_line_int(d.get('uom_id'))
    item.product_id = product_id
    item.amount = amount
    item.vat_category = d.get('vat_category') or None
    item.vat_rate = vat_rate
    item.wt_id = _so_line_int(d.get('wt_id'))
    item.delivery_date = _so_line_date(d.get('delivery_date'))
    item.delivery_site_id = _so_line_delivery_site_id(so, d.get('delivery_site_id'))
    item.calculate_amounts()
    return True


def _parse_and_attach_so_lines(so, lines_json):
    """Parse hidden-JSON line array and attach SalesOrderItem objects to *so*.
    Mirrors sales_invoices.views._parse_and_attach_line_items but with no account_id/wt.
    """
    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for idx, d in enumerate(items, start=1):
        li = SalesOrderItem()
        if not _assign_so_line_fields(so, li, d, idx):
            continue  # blank trailing line
        kept += 1
        li.line_number = kept
        so.line_items.append(li)


def _apply_amended_so_lines(so, lines_json):
    """Update this SO's lines IN PLACE from the submitted JSON.

    Unlike _parse_and_attach_so_lines (which the draft edit path uses after a
    wholesale delete), this preserves SalesOrderItem.id for every line the user
    kept -- the identity the revision diff matches on -- and therefore also
    preserves line_status and its closed_by/closed_at/closed_reason companions,
    which a rebuild would silently reset to 'open'.

    A submitted line carries `so_item_id` when it came from an existing row and
    null when the user added it in this amendment. Any existing row whose id is
    absent from the submission was removed by the user and is deleted.

    SECURITY: the lookup is scoped to THIS order's own so.line_items only -- an
    so_item_id belonging to a DIFFERENT Sales Order is never resolved against a
    global query, so it cannot rewrite another order's row. It simply falls
    through to "not found" and creates a new line on this order instead.
    """
    items = json.loads(lines_json) if lines_json else []
    existing = {item.id: item for item in so.line_items}
    seen = set()
    kept = 0

    for idx, d in enumerate(items, start=1):
        raw_id = d.get('so_item_id')
        try:
            item_id = int(raw_id) if raw_id not in (None, '', 'null') else None
        except (ValueError, TypeError):
            item_id = None

        item = existing.get(item_id) if item_id is not None else None
        if item is None:
            item = SalesOrderItem(sales_order_id=so.id)
            is_new = True
        else:
            is_new = False

        if not _assign_so_line_fields(so, item, d, idx):
            continue  # blank trailing line -- do not attach/keep it
        kept += 1
        item.line_number = kept

        if is_new:
            db.session.add(item)
            so.line_items.append(item)
        else:
            seen.add(item.id)

    # Iterate the PRE-LOOP `existing` snapshot, never the live collection.
    #
    # A newly added row starts with id None, but it does not stay that way: the
    # loop above calls _so_line_delivery_site_id -> db.session.get(...), and on a
    # cache miss SQLAlchemy AUTOFLUSHES before the SELECT, INSERTing the pending
    # new row and assigning it an id. That id was never added to `seen` (only
    # matched EXISTING ids are), so a sweep over the LIVE collection would DELETE
    # THE LINE THE USER JUST ADDED -- silently, with a success flash, and with the
    # loss baked into the revision snapshot as though it were intentional.
    # Reading `existing` is equivalent for real removals and immune to autoflush,
    # because it was captured before the loop ever ran.
    for item_id, item in existing.items():
        if item_id not in seen:
            so.line_items.remove(item)
            db.session.delete(item)


# Per-branch suffix appended to the numeric SO number (owner directive, 2026-07-29).
# CORP is the default/no-suffix branch; any branch not listed here also gets no suffix.
SO_NUMBER_BRANCH_SUFFIX = {'EXTRA': 'E'}


def generate_so_number(branch, order_date):
    """Next SO number for `branch` in `order_date`'s month: YYYYMM + 4-digit
    sequence + the branch's suffix (e.g. '2025120001' for CORP, '2025120001E'
    for EXTRA). The sequence resets every month and is scoped per branch --
    CORP and EXTRA each start fresh at 0001 independently. Legacy/manually
    typed numbers that don't match this exact shape are ignored, so they
    don't perturb the count (mirrors generate_invoice_number's contract of
    only counting purely-numeric-shaped existing numbers).
    """
    yyyymm = f'{order_date.year:04d}{order_date.month:02d}'
    suffix = SO_NUMBER_BRANCH_SUFFIX.get(branch.code, '')
    rows = SalesOrder.query.filter(
        SalesOrder.branch_id == branch.id,
        SalesOrder.so_number.like(f'{yyyymm}%')
    ).with_entities(SalesOrder.so_number).all()
    seqs = []
    for (num,) in rows:
        body = num[len(yyyymm):]
        if suffix:
            if not body.endswith(suffix):
                continue
            body = body[:-len(suffix)]
        if body.isdigit():
            seqs.append(int(body))
    next_seq = (max(seqs) + 1) if seqs else 1
    return f'{yyyymm}{next_seq:04d}{suffix}'


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
    delivery_sites = (CustomerDeliverySite.query.filter_by(is_active=True)
                       .order_by(CustomerDeliverySite.name).all())
    return {
        'units': [u.to_dict() for u in get_active_units()],
        'products': [p.to_dict() for p in get_active_products()],
        'vat_categories': [v.to_dict() for v in get_sales_vat_categories()],
        'customers': customers,
        # All active CustomerDeliverySite rows across all customers, each tagged with its
        # own customer_id -- filtered client-side to the header's selected customer, same
        # flat-list approach already used for products/units (Task 5).
        'delivery_sites': [s.to_dict() for s in delivery_sites],
        'customer_quick_add_form': build_customer_quick_add_form(),
        'customer_quick_add_whts': WithholdingTax.query.filter_by(is_active=True)
                                   .order_by(WithholdingTax.code).all(),
    }


# ── routes ───────────────────────────────────────────────────────────────────

@sales_orders_bp.route('/sales-orders/monitor')
@login_required
def monitor():
    """Order Monitoring -- a per-line-item SO/DR delivery-status view,
    grouped by customer (branch-scoped). The date range only controls
    which Sales Orders are included; DR/Undelivered figures are always
    all-time cumulative for whichever SOs make the cut."""
    branch_id = session.get('selected_branch_id')
    if not branch_id:
        flash('Please select a branch first.', 'error')
        return redirect(url_for('users.select_branch', next=request.url))

    from calendar import monthrange
    today = ph_now().date()
    default_from = today.replace(day=1)
    default_to = today.replace(day=monthrange(today.year, today.month)[1])
    try:
        date_from = date.fromisoformat(request.args.get('date_from', ''))
    except ValueError:
        date_from = default_from
    try:
        date_to = date.fromisoformat(request.args.get('date_to', ''))
    except ValueError:
        date_to = default_to

    from app.sales_orders.monitoring import get_order_monitoring
    data = get_order_monitoring(branch_id, date_from, date_to)
    return render_template('sales_orders/monitoring.html', date_from=date_from, date_to=date_to, **data)


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

    from app.sales_orders.utils import compute_sales_orders_summary
    summary = compute_sales_orders_summary(branch_id)

    return render_template('sales_orders/list.html',
                           orders=pagination.items,
                           pagination=pagination,
                           customers=customers,
                           summary=summary,
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
        form.order_date.data = ph_now().date()
        branch = db.session.get(Branch, session.get('selected_branch_id'))
        form.so_number.data = generate_so_number(branch, form.order_date.data)

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


@sales_orders_bp.route('/sales-orders/<int:id>/amend', methods=['GET', 'POST'])
@login_required
def amend(id):
    """Post-confirm amendment. Mirrors edit(), but the SO stays confirmed and
    every save appends a SalesOrderRevision."""
    gate = _role_gate()
    if gate:
        return gate

    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)
    if so.status != 'confirmed':
        flash('Only confirmed Sales Orders can be amended.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    po_required = bool(so.customer and so.customer.po_required)
    form = SalesOrderAmendForm(obj=so, po_required=po_required)
    form.salesperson_id.choices = _salesperson_choices(session.get('selected_branch_id'))

    restore_items = ([item.to_dict() for item in so.line_items]
                     if request.method == 'GET'
                     else json.loads(request.form.get('line_items', '[]') or '[]'))

    def _render():
        return render_template('sales_orders/form.html', form=form, so=so,
                               amend_mode=True, line_items=restore_items,
                               **_common_form_ctx())

    if form.validate_on_submit():
        submitted_lines = json.loads(request.form.get('line_items', '[]') or '[]')

        errors = validate_amendment(so, submitted_lines)
        if errors:
            for message in errors:
                flash(message, 'error')
            return _render()

        try:
            customer_id = int(form.customer_id.data)
        except (ValueError, TypeError):
            flash('Invalid customer.', 'error')
            return _render()

        cust = db.session.get(Customer, customer_id)
        if not cust:
            flash('Selected customer not found.', 'error')
            return _render()

        try:
            if not claim_version(SalesOrder, so.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('sales_orders', so.id), 'error')
                return _render()

            old_values = model_to_dict(so, [
                'so_number', 'order_date', 'customer_name',
                'subtotal', 'vat_amount', 'total_amount', 'status'])

            # so_number is deliberately NOT reassigned (an amendment revises an
            # order, it does not renumber it) -- but order_date is an ordinary
            # editable field and must not be silently discarded.
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

            # UPDATE IN PLACE -- do NOT delete-and-rebuild the way edit() does.
            # A rebuild resets line_status to 'open', silently RE-OPENING a line
            # someone deliberately short-closed and discarding closed_by_id /
            # closed_at / closed_reason with it. Per-line close is the module's
            # existing mechanism for stopping delivery on a tranche; an
            # amendment must not quietly undo it.
            # (It also keeps SalesOrderItem.id stable across revisions, so two
            # snapshots can be lined up by row when a reader compares them.)
            _apply_amended_so_lines(so, request.form.get('line_items', '[]'))
            db.session.flush()
            db.session.expire(so, ['line_items'])
            so.calculate_totals()

            rev = write_revision(
                so, current_user.id,
                reason=(form.amend_reason.data or '').strip(),
                authorizing_po=(form.authorizing_po_number.data or '').strip() or None)
            db.session.commit()

            log_update(
                module='sales_orders', record_id=so.id,
                record_identifier=f'{so.so_number} - {so.customer_name}',
                old_values=old_values,
                new_values=model_to_dict(so, [
                    'so_number', 'order_date', 'customer_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status']),
                notes=f'Amended to Rev {rev.revision_number}')

            flash(f'Sales Order "{so.so_number}" amended '
                  f'(Rev {rev.revision_number}).', 'success')
            return redirect(url_for('sales_orders.view', id=so.id))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return _render()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error amending sales order', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_orders.amend')
            flash('An error occurred while saving the amendment. Please try again.', 'error')

    elif request.method == 'POST':
        # form.validate_on_submit() failed on a real submission (not the initial
        # GET). A WTForms field-level ValidationError -- e.g.
        # validate_authorizing_po_number's -- only populates form.<field>.errors,
        # and the amend form template does not yet render per-field errors for
        # amend_reason/authorizing_po_number. Without this, that refusal reason
        # would silently vanish: the response would be a plain 200 with nothing
        # to distinguish it from any other refusal. Flash it explicitly, mirroring
        # how validate_amendment's errors are already surfaced above.
        for field_errors in form.errors.values():
            for message in field_errors:
                flash(message, 'error')

    return _render()


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


@sales_orders_bp.route('/sales-orders/<so_number>/print-job-order')
@login_required
def print_job_order(so_number):
    """Operations-facing Job Order Slip -- same SalesOrder record as print_so, no pricing,
    uses each line's Product.job_order_name (falling back to Product.name) instead of the
    name that prints on the DR/SI. Not gated by so_print_form -- that setting controls the
    accounting SO print form only. Keyed by so_number (unique, business-facing) rather than
    the internal id -- shop-floor staff reference the document by its printed number."""
    so = SalesOrder.query.filter_by(so_number=so_number).first_or_404()
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    created_by_user = (db.session.get(User, so.created_by_id)
                       if so.created_by_id else None)
    return render_template('sales_orders/print_job_order.html', so=so,
                           company=company, created_by_user=created_by_user,
                           printed_at=ph_now())


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
    # Rev 0 -- the baseline every later amendment is measured against, and the
    # snapshot that reproduces the job order slip issued to production.
    write_revision(so, current_user.id)
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


@sales_orders_bp.route('/sales-orders/<int:id>/lines/<int:item_id>/close', methods=['POST'])
@login_required
def close_line(id, item_id):
    """Close ONE line's remaining quantity (independent of the header cancel).
    Does not touch quantity/amount/delivery history -- so_line_open_qty() reads
    line_status to report 0 undelivered for this line going forward."""
    so = db.get_or_404(SalesOrder, id)
    if so.branch_id != session.get('selected_branch_id'):
        abort(404)
    item = db.session.get(SalesOrderItem, item_id)
    if item is None or item.sales_order_id != so.id:
        abort(404)

    # Role guard: accountant/admin (mirrors cancel()'s gate exactly)
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to close a Sales Order line.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    # Only a confirmed SO has lines worth closing -- a draft SO's lines are edited
    # directly, and a cancelled/closed SO's lines are already fully closed via
    # so_line_open_qty()'s header-status check.
    if so.status != 'confirmed':
        flash('Only lines on a confirmed Sales Order can be closed.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    if item.line_status == 'closed':
        flash('This line is already closed.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    # Note: unlike cancel()'s P-60 billed guard (so.sales_invoice_id), close_line
    # intentionally does NOT check whether the SO has been billed -- closing a line is
    # forward-looking (it only blocks further delivery/billing of the line's remaining
    # open qty) and touches no posted accounting, so it is safe on a billed SO too.

    # Guard: a DRAFT Delivery Receipt already references this line. so_line_open_qty()
    # returns 0 unconditionally once line_status == 'closed', bypassing the
    # exclude_dr_id re-check the DR-approve route relies on to stay idempotent -- so
    # closing here would strand that draft DR, permanently un-approvable with a
    # misleading "exceeds the open quantity 0" message (there is no un-close route;
    # recovery would require DB surgery). Refuse the close instead.
    #
    # Narrowed to status == 'draft' (not != 'cancelled'): approve() and edit() are the
    # only call sites that re-check open qty via exclude_dr_id (delivery_receipts/views.py
    # ~301), and both refuse anything not 'draft'. An approved/delivered/billed DR is
    # already committed and can never be stranded by closing the line -- and blocking on
    # those statuses would make short-closing a line after a partial delivery (the
    # feature's primary use case) unreachable.
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    draft_dr = (DeliveryReceiptItem.query
                .join(DeliveryReceipt, DeliveryReceiptItem.delivery_receipt_id == DeliveryReceipt.id)
                .filter(DeliveryReceiptItem.sales_order_item_id == item.id,
                        DeliveryReceipt.status == 'draft')
                .first())
    if draft_dr is not None:
        flash('This line has a pending (draft) Delivery Receipt referencing it -- approve '
              'or cancel that Delivery Receipt before closing the line.', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    closed_reason = request.form.get('closed_reason', '').strip()
    if len(closed_reason) < 10:
        flash('Please provide a reason (at least 10 characters).', 'error')
        return redirect(url_for('sales_orders.view', id=id))

    old_values = {'line_status': item.line_status}
    item.line_status = 'closed'
    item.closed_by_id = current_user.id
    item.closed_at = ph_now()
    item.closed_reason = closed_reason
    db.session.commit()

    log_update(
        module='sales_orders',
        record_id=so.id,
        record_identifier=so.so_number,
        old_values=old_values,
        new_values={'line_status': item.line_status},
        notes=f'Line {item.line_number} closed: {closed_reason}',
    )

    flash(f'Line {item.line_number} of "{so.so_number}" has been closed.', 'success')
    return redirect(url_for('sales_orders.view', id=id))
