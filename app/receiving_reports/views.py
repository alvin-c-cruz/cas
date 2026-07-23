"""Receiving Report views -- goods received against an approved Purchase Order.
Buy-side mirror of app/delivery_receipts/views.py. Approving a RR posts a GRNI accrual
JE (Dr Inventory / Cr GRNI, net of VAT) for tracked-inventory lines via
app.receiving_reports.stock_posting.post_rr_receipt -- a no-op for untracked lines.
The open-qty grid caps received qty at each PO line's OPEN quantity (checked at approve)."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, jsonify)
from flask_login import login_required, current_user

from app import db
from app.receiving_reports.models import (
    ReceivingReport, ReceivingReportItem, po_line_open_qty, generate_rr_number)
from app.receiving_reports.forms import ReceivingReportForm
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.settings import AppSettings
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.utils import ph_now
from app.utils.concurrency import claim_version, conflict_message, submitted_version

receiving_reports_bp = Blueprint('receiving_reports', __name__, template_folder='templates')

VALID_RR_STATUSES = {'draft', 'approved', 'billed', 'cancelled'}

# Approved POs are receivable; 'partially_received' too once that transition ships.
RECEIVABLE_PO_STATUSES = ('approved', 'partially_received')


# -- gates ---------------------------------------------------------------------

def _rr_role_gate():
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to manage Receiving Reports.', 'error')
        return redirect(url_for('receiving_reports.list_rr'))
    return None


def _approve_role_gate():
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only an approver (accountant/admin) can approve Receiving Reports.', 'error')
        return False
    return True


# -- form context --------------------------------------------------------------

def _eligible_purchase_orders(branch_id):
    """Approved POs in this branch that still have at least one line with open qty."""
    pos = (PurchaseOrder.query
           .filter(PurchaseOrder.branch_id == branch_id,
                   PurchaseOrder.status.in_(RECEIVABLE_PO_STATUSES))
           .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()).all())
    return [po for po in pos if any(po_line_open_qty(li) > 0 for li in po.line_items)]


def _po_lines_payload(eligible, exclude_rr_id=None):
    """{po_id: [line dicts]} for the create/edit form's open-qty grid."""
    payload = {}
    for po in eligible:
        rows = []
        for li in po.line_items:
            open_qty = po_line_open_qty(li, exclude_rr_id=exclude_rr_id)
            ordered = Decimal(str(li.quantity or 0))
            rows.append({
                'purchase_order_item_id': li.id,
                'product_code': li.product.code if li.product else '',
                'product_name': (li.product.name if li.product else (li.description or '')),
                'uom': (li.unit_of_measure.code if li.unit_of_measure else (li.uom_text or '')),
                'ordered': float(ordered),
                'received': float(ordered - open_qty),
                'open': float(open_qty),
            })
        payload[po.id] = rows
    return payload


def _existing_lines(rr):
    if not rr:
        return {}
    return {li.purchase_order_item_id: float(li.received_quantity) for li in rr.line_items}


def _submitted_existing_lines():
    """Rebuild {purchase_order_item_id: received_qty} from the POSTed hidden JSON (bounced edit)."""
    try:
        items = json.loads(request.form.get('lines', '[]') or '[]')
    except (ValueError, TypeError):
        return {}
    out = {}
    for d in items:
        poi_id = d.get('purchase_order_item_id')
        if not poi_id:
            continue
        try:
            out[int(poi_id)] = float(d.get('received_quantity') or 0)
        except (TypeError, ValueError):
            continue
    return out


def _render_edit(rr, form, eligible):
    existing = (_submitted_existing_lines() if request.method == 'POST'
                else _existing_lines(rr))
    return render_template('receiving_reports/form.html', form=form, rr=rr,
                           eligible=eligible,
                           po_lines=_po_lines_payload(eligible, exclude_rr_id=rr.id),
                           existing=existing)


def _parse_rr_lines(rr, lines_json):
    """Attach RR lines from the hidden JSON: [{purchase_order_item_id, received_quantity}]."""
    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for d in items:
        try:
            qty = Decimal(str(d.get('received_quantity')))
        except (InvalidOperation, TypeError):
            qty = Decimal('0')
        poi_id = d.get('purchase_order_item_id')
        if not poi_id or qty <= 0:
            continue
        kept += 1
        poi = db.session.get(PurchaseOrderItem, int(poi_id))
        rr.line_items.append(ReceivingReportItem(
            line_number=kept, purchase_order_item_id=int(poi_id),
            product_id=(poi.product_id if poi else None),
            received_quantity=qty))
    if kept == 0:
        raise ValueError('Add at least one received line.')


def _rr_or_404(id):
    rr = db.get_or_404(ReceivingReport, id)
    if rr.branch_id != session.get('selected_branch_id'):
        abort(404)
    return rr


# -- routes --------------------------------------------------------------------

def _filtered_rr_query(include_ids=False):
    """Build a branch-scoped ReceivingReport query from request filter args.

    Args read: status, vendor, q, date_from, date_to -- and ids when
    include_ids=True (exports only); a valid ids list overrides all other
    filters but stays branch-scoped. Invalid values are ignored.
    """
    branch_id = session.get('selected_branch_id')
    query = ReceivingReport.query.filter_by(branch_id=branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(ReceivingReport.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_RR_STATUSES:
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
        query = query.filter(db.or_(ReceivingReport.rr_number.ilike(like),
                                    ReceivingReport.vendor_name.ilike(like)))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(ReceivingReport.receipt_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(ReceivingReport.receipt_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@receiving_reports_bp.route('/receiving-reports')
@login_required
def list_rr():
    from app.receiving_reports.utils import compute_rr_summary
    from app.vendors.models import Vendor

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = _filtered_rr_query().order_by(ReceivingReport.receipt_date.desc(),
                                          ReceivingReport.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    branch_id = session.get('selected_branch_id')
    summary = compute_rr_summary(branch_id)
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('receiving_reports/list.html',
                           rr_list=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           status_filter=request.args.get('status', 'all'),
                           vendor_filter=request.args.get('vendor', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))


@receiving_reports_bp.route('/receiving-reports/billable')
@login_required
def billable_rrs():
    """JSON: approved, unbilled RRs for a vendor -- the goods billing path. Auto-gated by the
    receiving_reports module (before_request), so it 404s when the module is off."""
    from app.purchase_billing import billable_rrs_for, ap_billing_consolidate
    branch_id = session.get('selected_branch_id')
    vendor_id = request.args.get('vendor_id', type=int)
    rrs = billable_rrs_for(branch_id, vendor_id) if vendor_id else []
    return jsonify({'consolidate': ap_billing_consolidate(), 'rrs': rrs})


@receiving_reports_bp.route('/receiving-reports/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _rr_role_gate()
    if gate:
        return gate
    branch_id = session.get('selected_branch_id')
    form = ReceivingReportForm()
    eligible = _eligible_purchase_orders(branch_id)
    form.purchase_order_id.choices = [(po.id, f'{po.po_number}: {po.vendor_name}') for po in eligible]

    if form.validate_on_submit():
        rr_number = (form.rr_number.data or '').strip()
        if ReceivingReport.query.filter(ReceivingReport.rr_number == rr_number).first():
            flash('Receiving Report number already exists.', 'error')
            return render_template('receiving_reports/form.html', form=form, rr=None,
                                   eligible=eligible, po_lines=_po_lines_payload(eligible),
                                   existing={})

        po = db.session.get(PurchaseOrder, form.purchase_order_id.data)
        if not po or po.branch_id != branch_id or po.status not in RECEIVABLE_PO_STATUSES:
            flash('Select a valid approved Purchase Order.', 'error')
            return render_template('receiving_reports/form.html', form=form, rr=None,
                                   eligible=eligible, po_lines=_po_lines_payload(eligible),
                                   existing={})
        try:
            rr = ReceivingReport(
                rr_number=rr_number, branch_id=branch_id,
                receipt_date=form.receipt_date.data, purchase_order_id=po.id,
                vendor_id=po.vendor_id, vendor_name=po.vendor_name,
                remarks=form.remarks.data or None, status='draft',
                created_by_id=current_user.id)
            _parse_rr_lines(rr, request.form.get('lines', '[]'))
            db.session.add(rr); db.session.commit()
            log_create(module='receiving_reports', record_id=rr.id,
                       record_identifier=f'{rr.rr_number} - {rr.vendor_name}',
                       new_values=model_to_dict(rr, ['rr_number', 'status', 'receipt_date']))
            flash(f'Receiving Report "{rr.rr_number}" created.', 'success')
            return redirect(url_for('receiving_reports.view', id=rr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        except Exception:
            db.session.rollback(); flash('An error occurred creating the Receiving Report.', 'error')

    if request.method == 'GET':
        form.rr_number.data = generate_rr_number(branch_id)
        form.receipt_date.data = ph_now().date()
        preselect = request.args.get('po', type=int)
        if preselect and any(po.id == preselect for po in eligible):
            form.purchase_order_id.data = preselect
    return render_template('receiving_reports/form.html', form=form, rr=None,
                           eligible=eligible, po_lines=_po_lines_payload(eligible), existing={})


@receiving_reports_bp.route('/receiving-reports/<int:id>')
@login_required
def view(id):
    rr = _rr_or_404(id)
    return render_template('receiving_reports/detail.html', rr=rr)


@receiving_reports_bp.route('/receiving-reports/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _rr_role_gate()
    if gate:
        return gate
    rr = _rr_or_404(id)
    if rr.status != 'draft':
        flash('Only a draft Receiving Report can be edited.', 'error')
        return redirect(url_for('receiving_reports.view', id=rr.id))
    branch_id = session.get('selected_branch_id')
    form = ReceivingReportForm(obj=rr)
    eligible = _eligible_purchase_orders(branch_id)
    if rr.purchase_order and rr.purchase_order not in eligible:
        eligible = [rr.purchase_order] + eligible
    form.purchase_order_id.choices = [(po.id, f'{po.po_number}: {po.vendor_name}') for po in eligible]

    if form.validate_on_submit():
        old = model_to_dict(rr, ['rr_number', 'status', 'receipt_date'])
        try:
            if not claim_version(ReceivingReport, rr.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('receiving_reports', rr.id), 'error')
                return _render_edit(rr, form, eligible)
            rr.receipt_date = form.receipt_date.data
            rr.remarks = form.remarks.data or None
            rr.line_items.clear()
            _parse_rr_lines(rr, request.form.get('lines', '[]'))
            db.session.commit()
            log_update(module='receiving_reports', record_id=rr.id,
                       record_identifier=f'{rr.rr_number} - {rr.vendor_name}', old_values=old,
                       new_values=model_to_dict(rr, ['rr_number', 'status', 'receipt_date']))
            flash(f'Receiving Report "{rr.rr_number}" updated.', 'success')
            return redirect(url_for('receiving_reports.view', id=rr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        except Exception:
            db.session.rollback(); flash('An error occurred updating the Receiving Report.', 'error')

    if request.method == 'GET':
        form.purchase_order_id.data = rr.purchase_order_id
    return _render_edit(rr, form, eligible)


# -- lifecycle transitions -----------------------------------------------------

@receiving_reports_bp.route('/receiving-reports/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    rr = _rr_or_404(id)
    if not _approve_role_gate():
        return redirect(url_for('receiving_reports.view', id=id))
    if rr.status != 'draft':
        flash('Only a draft Receiving Report can be approved.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    # Guard: committing these lines must not exceed each PO line's OPEN qty.
    # `open` excludes THIS rr so a re-check stays idempotent.
    for li in rr.line_items:
        open_qty = po_line_open_qty(li.purchase_order_item, exclude_rr_id=rr.id)
        if Decimal(str(li.received_quantity)) > open_qty:
            poi = li.purchase_order_item
            item = (poi.product.name if (poi and poi.product) else (poi.description if poi else 'item'))
            flash(f'Line {li.line_number}: receiving {li.received_quantity} exceeds the open '
                  f'quantity {open_qty} for {item}.', 'error')
            return redirect(url_for('receiving_reports.view', id=id))
    rr.status = 'approved'
    rr.approved_by_id = current_user.id
    rr.approved_at = ph_now()
    from app.receiving_reports.stock_posting import post_rr_receipt
    from app.posting.control_accounts import ControlAccountError
    try:
        post_rr_receipt(rr, current_user)
    except (ValueError, ControlAccountError) as e:
        db.session.rollback()
        flash(str(e), 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    db.session.commit()
    log_audit(module='receiving_reports', action='approve', record_id=rr.id,
              record_identifier=rr.rr_number, notes='Approved')
    flash(f'Receiving Report "{rr.rr_number}" approved.', 'success')
    return redirect(url_for('receiving_reports.view', id=id))


@receiving_reports_bp.route('/receiving-reports/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    rr = _rr_or_404(id)
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only accountant/admin can cancel a Receiving Report.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    if rr.status == 'billed':
        flash('A billed Receiving Report cannot be cancelled.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    if rr.status == 'cancelled':
        flash('This Receiving Report is already cancelled.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    rr.status = 'cancelled'
    rr.cancelled_by_id = current_user.id
    rr.cancelled_at = ph_now()
    rr.cancel_reason = reason
    from app.receiving_reports.stock_posting import reverse_rr_receipt
    try:
        reverse_rr_receipt(rr, current_user)
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    db.session.commit()   # cancelling drops it out of COMMITTED_STATUSES -> qty released
    log_audit(module='receiving_reports', action='update', record_id=rr.id,
              record_identifier=rr.rr_number, notes=f'Cancelled: {reason}')
    flash(f'Receiving Report "{rr.rr_number}" cancelled.', 'warning')
    return redirect(url_for('receiving_reports.view', id=id))


# -- print ---------------------------------------------------------------------

@receiving_reports_bp.route('/receiving-reports/<int:id>/print')
@login_required
def print_rr(id):
    rr = _rr_or_404(id)
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    return render_template('receiving_reports/print.html', rr=rr, company=company,
                           printed_at=ph_now())


# -- export --------------------------------------------------------------------

_EXPORT_COLUMNS = ['rr_number', 'receipt_date', 'vendor_name', 'status']
_EXPORT_HEADERS = ['RR #', 'Receipt Date', 'Vendor', 'Status']


@receiving_reports_bp.route('/receiving-reports/export/excel')
@login_required
def export_excel():
    from app.utils.export import export_to_excel
    rows = _filtered_rr_query(include_ids=True).order_by(ReceivingReport.receipt_date.desc()).all()
    log_audit('receiving_reports', 'export_excel', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                           filename=f'receiving_reports_{timestamp}.xlsx',
                           title='Receiving Reports Report')


@receiving_reports_bp.route('/receiving-reports/export/csv')
@login_required
def export_csv_route():
    from app.utils.export import export_to_csv
    rows = _filtered_rr_query(include_ids=True).order_by(ReceivingReport.receipt_date.desc()).all()
    log_audit('receiving_reports', 'export_csv', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                         filename=f'receiving_reports_{timestamp}.csv')
