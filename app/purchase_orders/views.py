"""Purchase Order views -- create/edit/list/view + lifecycle. Buy-side mirror of
app/sales_orders/views.py. Operational module only: posts NO journal entry, has NO GL
account, NO WHT, NO payment. The Bill (Accounts Payable) is the first document that hits
the ledger. Lines accept a Product (goods) OR a free-text description (services)."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, current_app, jsonify)
from flask_login import login_required, current_user

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem, generate_po_number
from app.purchase_orders.forms import PurchaseOrderForm, PurchaseOrderAmendForm
from app.vendors.models import Vendor
from app.users.models import User
from app.settings import AppSettings
from app.amendments.service import write_revision
from app.amendments.validation import validate_amendment
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.cache_helpers import get_active_units, get_active_products, get_vat_categories
from app.utils.concurrency import claim_version, conflict_message, submitted_version

purchase_orders_bp = Blueprint('purchase_orders', __name__, template_folder='templates')

VALID_PO_STATUSES = {'draft', 'approved', 'partially_received', 'closed', 'cancelled'}


# ── line-item helpers ────────────────────────────────────────────────────────

def _po_line_dec(v):
    try:
        return Decimal(str(v)) if v not in (None, '', 'null') else None
    except (InvalidOperation, TypeError):
        return None


def _po_line_int(v):
    try:
        return int(v) if v and str(v).strip() not in ('', 'null') else None
    except (ValueError, TypeError):
        return None


def _assign_po_line_fields(item, d, idx):
    """Coerce one submitted line dict onto *item*. A line needs a Product (goods)
    OR a free-text description (services).

    Shared by BOTH line paths -- _parse_and_attach_po_lines (draft edit,
    rebuild-from-scratch) and _apply_amended_po_lines (post-approval amend,
    update in place) -- so the coercion rules live in exactly one place. Does NOT
    touch line_number (each caller assigns it once it knows how many non-blank
    lines it has kept) or received_quantity/billed_quantity (not form fields).

    *idx* is the line's 1-based position in the SUBMITTED array, used only in the
    raised ValueError's message. Returns False (leaving *item* untouched) for a
    blank trailing line; True otherwise.
    """
    vat_rate = _po_line_dec(d.get('vat_rate')) or Decimal('0.00')
    product_id = _po_line_int(d.get('product_id'))
    description = (d.get('description') or '').strip() or None
    amount = Decimal(str(d.get('amount', '0') or '0'))
    qty = _po_line_dec(d.get('quantity'))
    price = _po_line_dec(d.get('unit_price'))
    is_empty = (product_id is None and description is None
                and (amount is None or amount == 0) and qty is None and price is None)
    if is_empty:
        return False  # skip a blank trailing line
    if product_id is None and description is None:
        raise ValueError(f'Line {idx}: enter a product or a description.')

    item.description = description
    item.quantity = qty
    item.unit_price = price
    item.uom_text = (d.get('uom_text') or None)
    item.unit_of_measure_id = _po_line_int(d.get('uom_id'))
    item.product_id = product_id
    item.amount = amount
    item.vat_category = d.get('vat_category') or None
    item.vat_rate = vat_rate
    item.calculate_amounts()
    return True


def _parse_and_attach_po_lines(po, lines_json):
    """Parse hidden-JSON line array and attach PurchaseOrderItem objects to *po*.
    A line needs a Product (goods) OR a free-text description (services)."""
    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for idx, d in enumerate(items, start=1):
        li = PurchaseOrderItem()
        if not _assign_po_line_fields(li, d, idx):
            continue  # skip a blank trailing line
        kept += 1
        li.line_number = kept
        po.line_items.append(li)


def _apply_amended_po_lines(po, lines_json):
    """Update this PO's lines IN PLACE from the submitted JSON.

    Unlike _parse_and_attach_po_lines (which the draft edit path uses after a
    wholesale DELETE of every row), this preserves PurchaseOrderItem.id for every
    line the user kept. That id is load-bearing twice over:

      * it is the identity two revision snapshots are lined up by, so a rebuild
        would make every amendment look like "all lines removed, all lines added";
      * ReceivingReportItem.purchase_order_item_id points at it. SQLite FK
        enforcement is OFF app-wide, so a rebuild does not error -- it silently
        strands every existing RR line, and the next po_line_open_qty() on one
        dereferences None and 500s, unrecoverable through the UI.

    A submitted line carries `po_item_id` when it came from an existing row and
    null when the user added it in this amendment -- the SAME key
    validate_amendment() parses on. Validation must mirror application: any
    existing row whose id is absent from the submission was removed by the user
    and is deleted here, which is exactly the case validate_amendment refuses
    when that line has receipts or references against it.

    SECURITY: the lookup is scoped to THIS order's own po.line_items -- a
    po_item_id belonging to a DIFFERENT Purchase Order is never resolved through
    a global query, so it cannot rewrite another order's row. It falls through to
    "not found" and creates a new line on this order instead.
    """
    items = json.loads(lines_json) if lines_json else []
    existing = {item.id: item for item in po.line_items}
    seen = set()
    kept = 0

    for idx, d in enumerate(items, start=1):
        item_id = _po_line_int(d.get('po_item_id'))
        item = existing.get(item_id) if item_id is not None else None
        is_new = item is None
        if is_new:
            item = PurchaseOrderItem(purchase_order_id=po.id)

        if not _assign_po_line_fields(item, d, idx):
            # For an EXISTING item this `continue` leaves it out of `seen`, so
            # the sync loop below deletes it -- an implicit "blank an existing
            # row to remove it" path. It is unreachable in practice only because
            # a blank submission also blanks quantity, and validate_amendment's
            # per-row parse refuses a missing/unreadable quantity before this
            # function is ever called. The two parsers must keep matching.
            continue  # blank trailing line -- do not attach/keep it
        kept += 1
        item.line_number = kept

        if is_new:
            db.session.add(item)
            po.line_items.append(item)
        else:
            seen.add(item.id)

    # Iterate the PRE-LOOP `existing` snapshot, never the live collection: a row
    # appended above can be autoflushed (and so assigned an id) mid-loop, and its
    # id was never added to `seen`, so a sweep over the LIVE collection would
    # delete the line the user just added -- silently, with a success flash.
    for item_id, item in existing.items():
        if item_id not in seen:
            po.line_items.remove(item)
            db.session.delete(item)


# ── role gate + helpers ───────────────────────────────────────────────────────

def _role_gate():
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('purchase_orders.list_po'))
    return None


def _get_po_or_404(id):
    po = db.get_or_404(PurchaseOrder, id)
    if po.branch_id != session.get('selected_branch_id'):
        abort(404)
    return po


def _active_vendors():
    return Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()


def _common_form_ctx():
    return {
        'units': [u.to_dict() for u in get_active_units()],
        'products': [p.to_dict() for p in get_active_products()],
        'vat_categories': [v.to_dict() for v in get_vat_categories()],
    }


# ── routes ───────────────────────────────────────────────────────────────────

def _filtered_po_query(include_ids=False):
    """Build a branch-scoped PurchaseOrder query from request filter args.

    Args read: status, vendor, q, date_from, date_to -- and ids when
    include_ids=True (exports only); a valid ids list overrides all other
    filters but stays branch-scoped. Invalid values are ignored.
    """
    branch_id = session.get('selected_branch_id')
    query = PurchaseOrder.query.filter_by(branch_id=branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(PurchaseOrder.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_PO_STATUSES:
        query = query.filter_by(status=status_filter)

    vendor_filter = request.args.get('vendor', 'all')
    if vendor_filter != 'all':
        try:
            query = query.filter_by(vendor_id=int(vendor_filter))
        except ValueError:
            pass

    q_text = request.args.get('q', '').strip()
    if q_text:
        like = f'%{q_text}%'
        query = query.filter(db.or_(PurchaseOrder.po_number.ilike(like),
                                    PurchaseOrder.vendor_name.ilike(like)))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(PurchaseOrder.order_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(PurchaseOrder.order_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@purchase_orders_bp.route('/purchase-orders')
@login_required
def list_po():
    from app.purchase_orders.utils import compute_po_summary
    from app.vendors.models import Vendor

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = _filtered_po_query().order_by(PurchaseOrder.order_date.desc(),
                                          PurchaseOrder.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    branch_id = session.get('selected_branch_id')
    summary = compute_po_summary(branch_id)
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('purchase_orders/list.html',
                           po_list=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           status_filter=request.args.get('status', 'all'),
                           vendor_filter=request.args.get('vendor', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))


@purchase_orders_bp.route('/purchase-orders/billable')
@login_required
def billable_pos():
    """JSON: approved, unbilled, RR-less POs for a vendor -- the services/direct billing path.
    Auto-gated by the purchase_orders module (before_request), so it 404s when the module is off.
    Data source for the AP form's billing picker."""
    from app.purchase_billing import billable_pos_for, ap_billing_consolidate
    branch_id = session.get('selected_branch_id')
    vendor_id = request.args.get('vendor_id', type=int)
    pos = billable_pos_for(branch_id, vendor_id) if vendor_id else []
    return jsonify({'consolidate': ap_billing_consolidate(), 'pos': pos})


@purchase_orders_bp.route('/purchase-orders/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _role_gate()
    if gate:
        return gate

    form = PurchaseOrderForm()
    vendors = _active_vendors()
    form.set_vendor_choices(vendors)

    if form.validate_on_submit():
        po_number = (form.po_number.data or '').strip()

        if PurchaseOrder.query.filter(PurchaseOrder.po_number == po_number).first():
            flash('Purchase Order number already exists.', 'error')
            return render_template('purchase_orders/form.html', form=form, po=None,
                                   line_items=[], vendors=vendors, **_common_form_ctx())

        vendor = db.session.get(Vendor, form.vendor_id.data)
        if not vendor:
            flash('Selected vendor not found.', 'error')
            return render_template('purchase_orders/form.html', form=form, po=None,
                                   line_items=[], vendors=vendors, **_common_form_ctx())

        try:
            po = PurchaseOrder(
                branch_id=session.get('selected_branch_id'),
                po_number=po_number,
                order_date=form.order_date.data,
                expected_date=form.expected_date.data or None,
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                vendor_tin=vendor.tin,
                vendor_address=vendor.address,
                vat_treatment=form.vat_treatment.data,
                payment_terms=form.payment_terms.data,
                reference=form.reference.data or None,
                notes=form.notes.data or '',
                status='draft',
                created_by_id=current_user.id,
            )
            _parse_and_attach_po_lines(po, request.form.get('line_items', '[]'))
            po.calculate_totals()
            db.session.add(po)
            db.session.commit()

            log_create(
                module='purchase_orders',
                record_id=po.id,
                record_identifier=f'{po.po_number} - {po.vendor_name}',
                new_values=model_to_dict(po, [
                    'po_number', 'order_date', 'vendor_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status']),
            )
            flash(f'Purchase Order "{po.po_number}" created successfully!', 'success')
            return redirect(url_for('purchase_orders.list_po'))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('purchase_orders/form.html', form=form, po=None,
                                   line_items=[], vendors=vendors, **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating purchase order', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_orders.create')
            flash('An error occurred while entering the Purchase Order. Please try again.', 'error')

    if request.method == 'GET':
        form.po_number.data = generate_po_number()
        form.order_date.data = ph_now().date()

    return render_template('purchase_orders/form.html', form=form, po=None,
                           line_items=[], vendors=vendors, **_common_form_ctx())


@purchase_orders_bp.route('/purchase-orders/<int:id>')
@login_required
def view(id):
    po = _get_po_or_404(id)
    created_by_user = (db.session.get(User, po.created_by_id) if po.created_by_id else None)
    approved_by_user = (db.session.get(User, po.approved_by_id) if po.approved_by_id else None)
    cancelled_by_user = (db.session.get(User, po.cancelled_by_id) if po.cancelled_by_id else None)
    return render_template('purchase_orders/detail.html', po=po,
                           created_by_user=created_by_user,
                           approved_by_user=approved_by_user,
                           cancelled_by_user=cancelled_by_user)


@purchase_orders_bp.route('/purchase-orders/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _role_gate()
    if gate:
        return gate

    po = _get_po_or_404(id)
    if po.status != 'draft':
        flash('Only draft Purchase Orders can be edited.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    form = PurchaseOrderForm(obj=po)
    vendors = _active_vendors()
    form.set_vendor_choices(vendors)

    restore_items = ([li.to_dict() for li in po.line_items]
                     if request.method == 'GET'
                     else json.loads(request.form.get('line_items', '[]') or '[]'))

    if form.validate_on_submit():
        po_number = (form.po_number.data or '').strip()
        if PurchaseOrder.query.filter(PurchaseOrder.po_number == po_number,
                                      PurchaseOrder.id != po.id).first():
            flash('Purchase Order number already exists.', 'error')
            return render_template('purchase_orders/form.html', form=form, po=po,
                                   line_items=restore_items, vendors=vendors, **_common_form_ctx())

        vendor = db.session.get(Vendor, form.vendor_id.data)
        if not vendor:
            flash('Selected vendor not found.', 'error')
            return render_template('purchase_orders/form.html', form=form, po=po,
                                   line_items=restore_items, vendors=vendors, **_common_form_ctx())

        try:
            old_values = model_to_dict(po, [
                'po_number', 'order_date', 'vendor_name',
                'subtotal', 'vat_amount', 'total_amount', 'status'])

            # Lost-update guard: the first write, before the line teardown below.
            if not claim_version(PurchaseOrder, po.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('purchase_orders', po.id), 'error')
                return render_template('purchase_orders/form.html', form=form, po=po,
                                       line_items=restore_items, vendors=vendors, **_common_form_ctx())

            po.po_number = po_number
            po.order_date = form.order_date.data
            po.expected_date = form.expected_date.data or None
            po.vendor_id = vendor.id
            po.vendor_name = vendor.name
            po.vendor_tin = vendor.tin
            po.vendor_address = vendor.address
            po.vat_treatment = form.vat_treatment.data
            po.payment_terms = form.payment_terms.data
            po.reference = form.reference.data or None
            po.notes = form.notes.data or ''

            db.session.execute(db.delete(PurchaseOrderItem)
                               .where(PurchaseOrderItem.purchase_order_id == po.id))
            _parse_and_attach_po_lines(po, request.form.get('line_items', '[]'))
            db.session.flush()
            db.session.expire(po, ['line_items'])
            po.calculate_totals()
            db.session.commit()

            log_update(
                module='purchase_orders',
                record_id=po.id,
                record_identifier=f'{po.po_number} - {po.vendor_name}',
                old_values=old_values,
                new_values=model_to_dict(po, [
                    'po_number', 'order_date', 'vendor_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status']))
            flash(f'Purchase Order "{po.po_number}" updated successfully!', 'success')
            return redirect(url_for('purchase_orders.view', id=po.id))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('purchase_orders/form.html', form=form, po=po,
                                   line_items=restore_items, vendors=vendors, **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error updating purchase order', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_orders.edit')
            flash('An error occurred while saving the Purchase Order. Please try again.', 'error')

    return render_template('purchase_orders/form.html', form=form, po=po,
                           line_items=restore_items, vendors=vendors, **_common_form_ctx())


@purchase_orders_bp.route('/purchase-orders/<int:id>/amend', methods=['GET', 'POST'])
@login_required
def amend(id):
    """Post-approval amendment. Mirrors edit(), but the PO keeps its status and
    every save appends a DocumentRevision."""
    gate = _role_gate()
    if gate:
        return gate

    po = _get_po_or_404(id)
    if po.status == 'draft':
        flash('A draft Purchase Order is edited, not amended.', 'error')
        return redirect(url_for('purchase_orders.edit', id=id))
    if po.status not in PurchaseOrder.AMEND_STATUSES:
        flash(f'A Purchase Order with status "{po.status}" cannot be amended.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    form = PurchaseOrderAmendForm(obj=po)
    vendors = _active_vendors()
    form.set_vendor_choices(vendors)

    restore_items = ([li.to_dict() for li in po.line_items]
                     if request.method == 'GET'
                     else json.loads(request.form.get('line_items', '[]') or '[]'))

    def _render():
        return render_template('purchase_orders/form.html', form=form, po=po,
                               amend_mode=True, line_items=restore_items,
                               vendors=vendors, **_common_form_ctx())

    if form.validate_on_submit():
        submitted_lines = json.loads(request.form.get('line_items', '[]') or '[]')

        # Validate BEFORE claiming the version. claim_version's conditional
        # UPDATE increments row_version as a side effect, so claiming first would
        # leave a pending write behind on a refusal that then just re-renders.
        errors = validate_amendment(po, submitted_lines, 'po_item_id')
        if errors:
            for message in errors:
                flash(message, 'error')
            return _render()

        vendor = db.session.get(Vendor, form.vendor_id.data)
        if not vendor:
            flash('Selected vendor not found.', 'error')
            return _render()

        try:
            if not claim_version(PurchaseOrder, po.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('purchase_orders', po.id), 'error')
                return _render()

            old_values = model_to_dict(po, [
                'po_number', 'order_date', 'vendor_name',
                'subtotal', 'vat_amount', 'total_amount', 'status'])

            # po_number is deliberately NOT reassigned (an amendment revises an
            # order, it does not renumber it) -- but order_date is an ordinary
            # editable field and must not be silently discarded.
            po.order_date = form.order_date.data
            po.expected_date = form.expected_date.data or None
            po.vendor_id = vendor.id
            po.vendor_name = vendor.name
            po.vendor_tin = vendor.tin
            po.vendor_address = vendor.address
            po.vat_treatment = form.vat_treatment.data
            po.payment_terms = form.payment_terms.data
            po.reference = form.reference.data or None
            po.notes = form.notes.data or ''

            # UPDATE IN PLACE -- do NOT delete-and-rebuild the way edit() does.
            # See _apply_amended_po_lines: a rebuild strands every
            # ReceivingReportItem.purchase_order_item_id, silently.
            _apply_amended_po_lines(po, request.form.get('line_items', '[]'))
            db.session.flush()
            db.session.expire(po, ['line_items'])
            po.calculate_totals()

            rev = write_revision(po, current_user.id,
                                 reason=(form.amend_reason.data or '').strip())
            db.session.commit()

            log_update(
                module='purchase_orders',
                record_id=po.id,
                record_identifier=f'{po.po_number} - {po.vendor_name}',
                old_values=old_values,
                new_values=model_to_dict(po, [
                    'po_number', 'order_date', 'vendor_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status']),
                notes=f'Amended to Rev {rev.revision_number}')

            flash(f'Purchase Order "{po.po_number}" amended '
                  f'(Rev {rev.revision_number}).', 'success')
            return redirect(url_for('purchase_orders.view', id=po.id))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return _render()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error amending purchase order', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_orders.amend')
            flash('An error occurred while saving the amendment. Please try again.', 'error')

    elif request.method == 'POST':
        # validate_on_submit() failed on a real submission. A WTForms field-level
        # error (e.g. amend_reason's Length) only populates form.<field>.errors,
        # and form.html does not render per-field errors for amend_reason -- so
        # without this the refusal reason vanishes and the response is a plain
        # 200 indistinguishable from a success.
        for field_errors in form.errors.values():
            for message in field_errors:
                flash(message, 'error')

    return _render()


@purchase_orders_bp.route('/purchase-orders/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    """Draft -> approved. No journal entry -- a PO posts nothing."""
    po = _get_po_or_404(id)
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to approve Purchase Orders.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if po.status != 'draft':
        flash('Only draft Purchase Orders can be approved.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if po.vendor_id is None:
        flash('Set a vendor before approving this Purchase Order.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if not any((li.unit_price or 0) > 0 and (li.amount or 0) > 0 for li in po.line_items):
        flash('Set a unit price on at least one line before approving this Purchase Order.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    old_values = model_to_dict(po, ['status'])
    po.status = 'approved'
    po.approved_by_id = current_user.id
    po.approved_at = ph_now()
    # Rev 0 -- the baseline every later amendment is measured against. Written
    # AFTER the status change so the snapshot records the PO as approved, and
    # inside the same transaction so approval and baseline land atomically.
    write_revision(po, current_user.id)
    db.session.commit()

    log_update(module='purchase_orders', record_id=po.id, record_identifier=po.po_number,
               old_values=old_values, new_values=model_to_dict(po, ['status']), notes='Approved')
    flash(f'Purchase Order "{po.po_number}" has been approved.', 'success')
    return redirect(url_for('purchase_orders.view', id=id))


@purchase_orders_bp.route('/purchase-orders/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    """Non-terminal PO -> cancelled. Captures a reason from the custom modal form."""
    po = _get_po_or_404(id)
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to cancel Purchase Orders.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if po.accounts_payable_id is not None:
        flash('A billed Purchase Order cannot be cancelled. Void the bill first.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if po.status in ('cancelled', 'closed'):
        flash('This Purchase Order has already been cancelled or closed.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Please provide a cancellation reason (at least 10 characters).', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    old_values = model_to_dict(po, ['status'])
    po.status = 'cancelled'
    po.cancelled_by_id = current_user.id
    po.cancelled_at = ph_now()
    po.cancel_reason = cancel_reason
    db.session.commit()

    log_update(module='purchase_orders', record_id=po.id, record_identifier=po.po_number,
               old_values=old_values, new_values=model_to_dict(po, ['status']),
               notes=f'Cancelled: {cancel_reason}')
    flash(f'Purchase Order "{po.po_number}" has been cancelled.', 'success')
    return redirect(url_for('purchase_orders.view', id=id))


@purchase_orders_bp.route('/purchase-orders/<int:id>/print')
@login_required
def print_po(id):
    po = _get_po_or_404(id)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('purchase_orders/print.html', po=po, company=company, printed_at=ph_now())


# ── export routes ────────────────────────────────────────────────────────────

_EXPORT_COLUMNS = ['po_number', 'order_date', 'vendor_name', 'vendor_tin', 'subtotal',
                   'vat_amount', 'total_amount', 'status']
_EXPORT_HEADERS = ['PO #', 'Order Date', 'Vendor', 'TIN', 'Subtotal', 'VAT', 'Total', 'Status']


@purchase_orders_bp.route('/purchase-orders/export/excel')
@login_required
def export_excel():
    from app.utils.export import export_to_excel
    rows = _filtered_po_query(include_ids=True).order_by(PurchaseOrder.order_date.desc()).all()
    log_audit('purchase_orders', 'export_excel', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                           filename=f'purchase_orders_{timestamp}.xlsx',
                           title='Purchase Orders Report')


@purchase_orders_bp.route('/purchase-orders/export/csv')
@login_required
def export_csv_route():
    from app.utils.export import export_to_csv
    rows = _filtered_po_query(include_ids=True).order_by(PurchaseOrder.order_date.desc()).all()
    log_audit('purchase_orders', 'export_csv', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                         filename=f'purchase_orders_{timestamp}.csv')
