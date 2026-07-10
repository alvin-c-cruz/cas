"""Delivery Receipt views -- deliveries against a confirmed Sales Order. Operational only."""
import json
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, abort
from flask_login import login_required, current_user

from app import db
from app.delivery_receipts.models import (
    DeliveryReceipt, DeliveryReceiptItem, so_line_open_qty, generate_dr_number)
from app.delivery_receipts.forms import DeliveryReceiptForm
from app.sales_orders.models import SalesOrder, SalesOrderItem, copy_salesperson
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.utils import ph_now
from app.utils.concurrency import claim_version, conflict_message, submitted_version

delivery_receipts_bp = Blueprint('delivery_receipts', __name__, template_folder='templates')

VALID_DR_STATUSES = {'draft', 'approved', 'delivered', 'billed', 'cancelled'}


# -- gates ---------------------------------------------------------------------

def _dr_role_gate():
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to manage Delivery Receipts.', 'error')
        return redirect(url_for('delivery_receipts.list'))
    return None


def _approve_role_gate():
    # TODO(Approver role): swap this interim gate for the dedicated Approver role when it ships.
    # has_full_access == admin or chief_accountant.
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only an approver (accountant/admin) can approve Delivery Receipts.', 'error')
        return False
    return True


# -- form context --------------------------------------------------------------

def _eligible_sales_orders(branch_id):
    """Confirmed SOs in this branch that still have at least one line with open qty."""
    sos = (SalesOrder.query.filter_by(branch_id=branch_id, status='confirmed')
           .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc()).all())
    return [so for so in sos if any(so_line_open_qty(li) > 0 for li in so.line_items)]


def _salesperson_choices(branch_id):
    from app.sales_orders.views import _salesperson_choices as so_choices
    return so_choices(branch_id)


def _so_lines_payload(eligible, exclude_dr_id=None):
    """{so_id: [line dicts]} for the create/edit form's open-qty grid."""
    payload = {}
    for so in eligible:
        rows = []
        for li in so.line_items:
            open_qty = so_line_open_qty(li, exclude_dr_id=exclude_dr_id)
            ordered = Decimal(str(li.quantity or 0))
            rows.append({
                'sales_order_item_id': li.id,
                'product_code': li.product.code if li.product else '',
                'product_name': li.product.name if li.product else '',
                'uom': (li.unit_of_measure.code if li.unit_of_measure else (li.uom_text or '')),
                'ordered': float(ordered),
                'delivered': float(ordered - open_qty),
                'open': float(open_qty),
            })
        payload[so.id] = rows
    return payload


def _existing_lines(dr):
    """{sales_order_item_id: delivered_qty} so the edit form pre-fills its grid."""
    if not dr:
        return {}
    return {li.sales_order_item_id: float(li.delivered_quantity) for li in dr.line_items}


def _submitted_existing_lines():
    """The same shape as _existing_lines(), rebuilt from the POSTed hidden JSON.

    On a bounced edit the grid must show what the encoder typed, not what the
    database holds -- otherwise a conflict banner claims their work is preserved
    while silently redisplaying someone else's quantities.
    """
    try:
        items = json.loads(request.form.get('lines', '[]') or '[]')
    except (ValueError, TypeError):
        return {}
    out = {}
    for d in items:
        soi_id = d.get('sales_order_item_id')
        if not soi_id:
            continue
        try:
            out[int(soi_id)] = float(d.get('delivered_quantity') or 0)
        except (TypeError, ValueError):
            continue
    return out


def _render_edit(dr, form, eligible):
    """Render the DR edit form, carrying submitted quantities back on a failed POST."""
    existing = (_submitted_existing_lines() if request.method == 'POST'
                else _existing_lines(dr))
    return render_template('delivery_receipts/form.html', form=form, dr=dr,
                           eligible=eligible,
                           so_lines=_so_lines_payload(eligible, exclude_dr_id=dr.id),
                           existing=existing)


def _parse_dr_lines(dr, lines_json):
    """Attach DR lines from the hidden JSON: [{sales_order_item_id, delivered_quantity}]."""
    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for d in items:
        try:
            qty = Decimal(str(d.get('delivered_quantity')))
        except (InvalidOperation, TypeError):
            qty = Decimal('0')
        soi_id = d.get('sales_order_item_id')
        if not soi_id or qty <= 0:
            continue
        kept += 1
        soi = db.session.get(SalesOrderItem, int(soi_id))
        dr.line_items.append(DeliveryReceiptItem(
            line_number=kept, sales_order_item_id=int(soi_id),
            product_id=(soi.product_id if soi else None),
            delivered_quantity=qty))
    if kept == 0:
        raise ValueError('Add at least one delivered line.')


def _dr_or_404(id):
    dr = db.get_or_404(DeliveryReceipt, id)
    if dr.branch_id != session.get('selected_branch_id'):
        abort(404)
    return dr


# -- routes --------------------------------------------------------------------

@delivery_receipts_bp.route('/delivery-receipts')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    query = DeliveryReceipt.query.filter_by(branch_id=branch_id)
    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_DR_STATUSES:
        query = query.filter_by(status=status_filter)
    receipts = query.order_by(DeliveryReceipt.delivery_date.desc(),
                              DeliveryReceipt.id.desc()).all()
    return render_template('delivery_receipts/list.html', receipts=receipts,
                           status_filter=status_filter)


@delivery_receipts_bp.route('/delivery-receipts/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _dr_role_gate()
    if gate:
        return gate
    branch_id = session.get('selected_branch_id')
    form = DeliveryReceiptForm()
    eligible = _eligible_sales_orders(branch_id)
    form.sales_order_id.choices = [(so.id, f'{so.so_number}: {so.customer_name}') for so in eligible]
    form.salesperson_id.choices = _salesperson_choices(branch_id)

    if form.validate_on_submit():
        so = db.session.get(SalesOrder, form.sales_order_id.data)
        if not so or so.branch_id != branch_id or so.status != 'confirmed':
            flash('Select a valid confirmed Sales Order.', 'error')
            return render_template('delivery_receipts/form.html', form=form, dr=None,
                                   eligible=eligible, so_lines=_so_lines_payload(eligible),
                                   existing=_existing_lines(None))
        try:
            dr = DeliveryReceipt(
                dr_number=generate_dr_number(branch_id), branch_id=branch_id,
                delivery_date=form.delivery_date.data, sales_order_id=so.id,
                customer_id=so.customer_id, customer_name=so.customer_name,
                remarks=form.remarks.data or None, status='draft',
                created_by_id=current_user.id)
            copy_salesperson(so, dr)
            if form.salesperson_id.data:   # allow override; 0 == Company Account
                dr.salesperson_id = form.salesperson_id.data
            _parse_dr_lines(dr, request.form.get('lines', '[]'))
            db.session.add(dr); db.session.commit()
            log_create(module='delivery_receipts', record_id=dr.id,
                       record_identifier=f'{dr.dr_number} - {dr.customer_name}',
                       new_values=model_to_dict(dr, ['dr_number', 'status', 'delivery_date']))
            flash(f'Delivery Receipt "{dr.dr_number}" created.', 'success')
            return redirect(url_for('delivery_receipts.view', id=dr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        except Exception:
            db.session.rollback(); flash('An error occurred creating the Delivery Receipt.', 'error')

    if request.method == 'GET':
        form.delivery_date.data = ph_now().date()
        preselect = request.args.get('so', type=int)
        if preselect and any(so.id == preselect for so in eligible):
            form.sales_order_id.data = preselect
    return render_template('delivery_receipts/form.html', form=form, dr=None,
                           eligible=eligible, so_lines=_so_lines_payload(eligible),
                           existing=_existing_lines(None))


@delivery_receipts_bp.route('/delivery-receipts/<int:id>')
@login_required
def view(id):
    dr = _dr_or_404(id)
    return render_template('delivery_receipts/detail.html', dr=dr)


@delivery_receipts_bp.route('/delivery-receipts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _dr_role_gate()
    if gate:
        return gate
    dr = _dr_or_404(id)
    if dr.status != 'draft':
        flash('Only a draft Delivery Receipt can be edited.', 'error')
        return redirect(url_for('delivery_receipts.view', id=dr.id))
    branch_id = session.get('selected_branch_id')
    form = DeliveryReceiptForm(obj=dr)
    eligible = _eligible_sales_orders(branch_id)
    if dr.sales_order and dr.sales_order not in eligible:
        eligible = [dr.sales_order] + eligible      # its own SO stays pickable while editing
    form.sales_order_id.choices = [(so.id, f'{so.so_number}: {so.customer_name}') for so in eligible]
    form.salesperson_id.choices = _salesperson_choices(branch_id)

    if form.validate_on_submit():
        old = model_to_dict(dr, ['dr_number', 'status', 'delivery_date'])
        try:
            # Lost-update guard: the first write, before dr.line_items.clear() below.
            # DR is the module that motivated an explicit row_version column: its
            # header carries no totals, so a line-only edit never dirties the row
            # and `updated_at`'s onupdate would never fire.
            if not claim_version(DeliveryReceipt, dr.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('delivery_receipts', dr.id), 'error')
                return _render_edit(dr, form, eligible)

            dr.delivery_date = form.delivery_date.data
            dr.remarks = form.remarks.data or None
            if form.salesperson_id.data:
                dr.salesperson_id = form.salesperson_id.data
            # Rebuild lines through the ORM collection so delete-orphan evicts the old
            # rows; a bulk Query.delete() would leave a stale cached relationship.
            dr.line_items.clear()
            _parse_dr_lines(dr, request.form.get('lines', '[]'))
            db.session.commit()
            log_update(module='delivery_receipts', record_id=dr.id,
                       record_identifier=f'{dr.dr_number} - {dr.customer_name}',
                       old_values=old,
                       new_values=model_to_dict(dr, ['dr_number', 'status', 'delivery_date']))
            flash(f'Delivery Receipt "{dr.dr_number}" updated.', 'success')
            return redirect(url_for('delivery_receipts.view', id=dr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        except Exception:
            db.session.rollback(); flash('An error occurred updating the Delivery Receipt.', 'error')

    if request.method == 'GET':
        form.sales_order_id.data = dr.sales_order_id
        form.salesperson_id.data = dr.salesperson_id or 0
    return _render_edit(dr, form, eligible)


# -- lifecycle transitions -----------------------------------------------------

@delivery_receipts_bp.route('/delivery-receipts/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    dr = _dr_or_404(id)
    if not _approve_role_gate():
        return redirect(url_for('delivery_receipts.view', id=id))
    if dr.status != 'draft':
        flash('Only a draft Delivery Receipt can be approved.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    # Guard: committing these lines must not exceed each SO line's OPEN qty.
    # `open` excludes THIS dr so a re-check stays idempotent.
    for li in dr.line_items:
        open_qty = so_line_open_qty(li.sales_order_item, exclude_dr_id=dr.id)
        if Decimal(str(li.delivered_quantity)) > open_qty:
            soi = li.sales_order_item
            prod = soi.product.name if (soi and soi.product) else 'item'
            flash(f'Line {li.line_number}: delivering {li.delivered_quantity} exceeds the open '
                  f'quantity {open_qty} for {prod}.', 'error')
            return redirect(url_for('delivery_receipts.view', id=id))
    dr.status = 'approved'
    dr.approved_by_id = current_user.id
    dr.approved_at = ph_now()
    db.session.commit()
    log_audit(module='delivery_receipts', action='approve', record_id=dr.id,
              record_identifier=dr.dr_number, notes='Approved')
    flash(f'Delivery Receipt "{dr.dr_number}" approved.', 'success')
    return redirect(url_for('delivery_receipts.view', id=id))


@delivery_receipts_bp.route('/delivery-receipts/<int:id>/deliver', methods=['POST'])
@login_required
def mark_delivered(id):
    dr = _dr_or_404(id)
    gate = _dr_role_gate()
    if gate:
        return gate
    if dr.status != 'approved':
        flash('Only an approved Delivery Receipt can be marked delivered.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    dr.status = 'delivered'
    dr.delivered_by_id = current_user.id
    dr.delivered_at = ph_now()
    db.session.commit()
    log_audit(module='delivery_receipts', action='update', record_id=dr.id,
              record_identifier=dr.dr_number, notes='Delivered')
    flash(f'Delivery Receipt "{dr.dr_number}" marked delivered.', 'success')
    return redirect(url_for('delivery_receipts.view', id=id))


@delivery_receipts_bp.route('/delivery-receipts/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    dr = _dr_or_404(id)
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only accountant/admin can cancel a Delivery Receipt.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    if dr.status == 'billed':
        flash('A billed Delivery Receipt cannot be cancelled.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    if dr.status == 'cancelled':
        flash('This Delivery Receipt is already cancelled.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    dr.status = 'cancelled'
    dr.cancelled_by_id = current_user.id
    dr.cancelled_at = ph_now()
    dr.cancel_reason = reason
    db.session.commit()   # cancelling drops it out of COMMITTED_STATUSES -> qty released
    log_audit(module='delivery_receipts', action='update', record_id=dr.id,
              record_identifier=dr.dr_number, notes=f'Cancelled: {reason}')
    flash(f'Delivery Receipt "{dr.dr_number}" cancelled.', 'warning')
    return redirect(url_for('delivery_receipts.view', id=id))


# -- print ---------------------------------------------------------------------

@delivery_receipts_bp.route('/delivery-receipts/<int:id>/print')
@login_required
def print_dr(id):
    from app.settings import AppSettings
    dr = _dr_or_404(id)
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    return render_template('delivery_receipts/print.html', dr=dr, company=company,
                           printed_at=ph_now())
