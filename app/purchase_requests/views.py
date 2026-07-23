"""Purchase Request views -- a thin requisition that converts to a draft PO on approval.
Mirror of app/quotations/views.py. Operational only: posts NO journal entry."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, current_app)
from flask_login import login_required, current_user

from app import db
from app.purchase_requests.models import (
    PurchaseRequest, PurchaseRequestItem, generate_pr_number)
from app.purchase_requests.forms import PurchaseRequestForm
from app.users.models import User
from app.settings import AppSettings
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.cache_helpers import get_active_units, get_active_products
from app.utils.concurrency import claim_version, conflict_message, submitted_version

purchase_requests_bp = Blueprint('purchase_requests', __name__, template_folder='templates')

VALID_PR_STATUSES = {'draft', 'submitted', 'approved', 'rejected', 'converted', 'cancelled'}


# -- gates ---------------------------------------------------------------------

def _pr_role_gate():
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to manage Purchase Requests.', 'error')
        return redirect(url_for('purchase_requests.list_pr'))
    return None


def _approve_gate():
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only an approver (accountant/admin) can approve Purchase Requests.', 'error')
        return False
    return True


def _get_pr_or_404(id):
    pr = db.get_or_404(PurchaseRequest, id)
    if pr.branch_id != session.get('selected_branch_id'):
        abort(404)
    return pr


def _common_form_ctx():
    return {
        'units': [u.to_dict() for u in get_active_units()],
        'products': [p.to_dict() for p in get_active_products()],
    }


def _parse_and_attach_pr_lines(pr, lines_json):
    """Attach requisition lines. A line needs a Product OR a free-text description; no pricing."""
    def _int(v):
        try:
            return int(v) if v and str(v).strip() not in ('', 'null') else None
        except (ValueError, TypeError):
            return None

    def _dec(v):
        try:
            return Decimal(str(v)) if v not in (None, '', 'null') else None
        except (InvalidOperation, TypeError):
            return None

    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for idx, d in enumerate(items, start=1):
        product_id = _int(d.get('product_id'))
        description = (d.get('description') or '').strip() or None
        qty = _dec(d.get('quantity'))
        if product_id is None and description is None and qty is None:
            continue  # blank line
        if product_id is None and description is None:
            raise ValueError(f'Line {idx}: enter a product or a description.')
        kept += 1
        pr.line_items.append(PurchaseRequestItem(
            line_number=kept, product_id=product_id, description=description,
            quantity=qty, unit_of_measure_id=_int(d.get('uom_id')),
            uom_text=(d.get('uom_text') or None)))
    if kept == 0:
        raise ValueError('Add at least one requested item.')


# -- routes --------------------------------------------------------------------

def _filtered_pr_query(include_ids=False):
    """Build a branch-scoped PurchaseRequest query from request filter args.

    Args read: status, q, date_from, date_to -- and ids when include_ids=True
    (exports only); a valid ids list overrides all other filters but stays
    branch-scoped. Invalid values are ignored.
    """
    branch_id = session.get('selected_branch_id')
    query = PurchaseRequest.query.filter_by(branch_id=branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(PurchaseRequest.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_PR_STATUSES:
        query = query.filter_by(status=status_filter)

    q = request.args.get('q', '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(PurchaseRequest.pr_number.ilike(like),
                                    PurchaseRequest.reason.ilike(like)))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(PurchaseRequest.request_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(PurchaseRequest.request_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@purchase_requests_bp.route('/purchase-requests')
@login_required
def list_pr():
    from app.purchase_requests.utils import compute_pr_summary

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = _filtered_pr_query().order_by(PurchaseRequest.request_date.desc(),
                                          PurchaseRequest.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    branch_id = session.get('selected_branch_id')
    summary = compute_pr_summary(branch_id)

    return render_template('purchase_requests/list.html',
                           pr_list=pagination.items,
                           pagination=pagination,
                           summary=summary,
                           status_filter=request.args.get('status', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))


@purchase_requests_bp.route('/purchase-requests/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _pr_role_gate()
    if gate:
        return gate
    form = PurchaseRequestForm()
    if form.validate_on_submit():
        pr_number = (form.pr_number.data or '').strip()
        if PurchaseRequest.query.filter(PurchaseRequest.pr_number == pr_number).first():
            flash('Purchase Request number already exists.', 'error')
            return render_template('purchase_requests/form.html', form=form, pr=None,
                                   line_items=[], **_common_form_ctx())
        try:
            pr = PurchaseRequest(
                branch_id=session.get('selected_branch_id'),
                pr_number=pr_number,
                request_date=form.request_date.data,
                reason=form.reason.data or None,
                status='draft', created_by_id=current_user.id)
            _parse_and_attach_pr_lines(pr, request.form.get('line_items', '[]'))
            db.session.add(pr); db.session.commit()
            log_create(module='purchase_requests', record_id=pr.id,
                       record_identifier=pr.pr_number,
                       new_values=model_to_dict(pr, ['pr_number', 'request_date', 'status']))
            flash(f'Purchase Request "{pr.pr_number}" created.', 'success')
            return redirect(url_for('purchase_requests.view', id=pr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
            return render_template('purchase_requests/form.html', form=form, pr=None,
                                   line_items=[], **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating purchase request', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_requests.create')
            flash('An error occurred creating the Purchase Request.', 'error')

    if request.method == 'GET':
        form.pr_number.data = generate_pr_number()
        form.request_date.data = ph_now().date()
    return render_template('purchase_requests/form.html', form=form, pr=None,
                           line_items=[], **_common_form_ctx())


@purchase_requests_bp.route('/purchase-requests/<int:id>')
@login_required
def view(id):
    pr = _get_pr_or_404(id)
    created_by_user = db.session.get(User, pr.created_by_id) if pr.created_by_id else None
    return render_template('purchase_requests/detail.html', pr=pr, created_by_user=created_by_user)


@purchase_requests_bp.route('/purchase-requests/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _pr_role_gate()
    if gate:
        return gate
    pr = _get_pr_or_404(id)
    if pr.status != 'draft':
        flash('Only a draft Purchase Request can be edited.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    form = PurchaseRequestForm(obj=pr)
    restore = ([li.to_dict() for li in pr.line_items] if request.method == 'GET'
               else json.loads(request.form.get('line_items', '[]') or '[]'))

    if form.validate_on_submit():
        old = model_to_dict(pr, ['pr_number', 'request_date', 'status'])
        try:
            if not claim_version(PurchaseRequest, pr.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('purchase_requests', pr.id), 'error')
                return render_template('purchase_requests/form.html', form=form, pr=pr,
                                       line_items=restore, **_common_form_ctx())
            pr.request_date = form.request_date.data
            pr.reason = form.reason.data or None
            pr.line_items.clear()
            _parse_and_attach_pr_lines(pr, request.form.get('line_items', '[]'))
            db.session.commit()
            log_update(module='purchase_requests', record_id=pr.id, record_identifier=pr.pr_number,
                       old_values=old, new_values=model_to_dict(pr, ['pr_number', 'request_date', 'status']))
            flash(f'Purchase Request "{pr.pr_number}" updated.', 'success')
            return redirect(url_for('purchase_requests.view', id=pr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        except Exception as e:
            db.session.rollback()
            log_exception(e, severity='ERROR', module='purchase_requests.edit')
            flash('An error occurred updating the Purchase Request.', 'error')
    return render_template('purchase_requests/form.html', form=form, pr=pr,
                           line_items=restore, **_common_form_ctx())


# -- lifecycle -----------------------------------------------------------------

@purchase_requests_bp.route('/purchase-requests/<int:id>/submit', methods=['POST'])
@login_required
def submit(id):
    pr = _get_pr_or_404(id)
    gate = _pr_role_gate()
    if gate:
        return gate
    if pr.status != 'draft':
        flash('Only a draft Purchase Request can be submitted.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    pr.status = 'submitted'
    pr.submitted_by_id = current_user.id
    pr.submitted_at = ph_now()
    db.session.commit()
    log_audit(module='purchase_requests', action='update', record_id=pr.id,
              record_identifier=pr.pr_number, notes='Submitted')
    flash(f'Purchase Request "{pr.pr_number}" submitted for approval.', 'success')
    return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    pr = _get_pr_or_404(id)
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status != 'submitted':
        flash('Only a submitted Purchase Request can be approved.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    pr.status = 'approved'
    pr.approved_by_id = current_user.id
    pr.approved_at = ph_now()
    db.session.commit()
    log_audit(module='purchase_requests', action='approve', record_id=pr.id,
              record_identifier=pr.pr_number, notes='Approved')
    flash(f'Purchase Request "{pr.pr_number}" approved. Convert it to a Purchase Order.', 'success')
    return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/reject', methods=['POST'])
@login_required
def reject(id):
    pr = _get_pr_or_404(id)
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status != 'submitted':
        flash('Only a submitted Purchase Request can be rejected.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    reason = (request.form.get('reject_reason') or '').strip()
    if len(reason) < 10:
        flash('A rejection reason (min 10 chars) is required.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    pr.status = 'rejected'
    pr.rejected_by_id = current_user.id
    pr.rejected_at = ph_now()
    pr.reject_reason = reason
    db.session.commit()
    log_audit(module='purchase_requests', action='update', record_id=pr.id,
              record_identifier=pr.pr_number, notes=f'Rejected: {reason}')
    flash(f'Purchase Request "{pr.pr_number}" rejected.', 'warning')
    return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    pr = _get_pr_or_404(id)
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status in ('converted', 'cancelled', 'rejected'):
        flash('This Purchase Request can no longer be cancelled.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    pr.status = 'cancelled'
    pr.cancelled_by_id = current_user.id
    pr.cancelled_at = ph_now()
    pr.cancel_reason = reason
    db.session.commit()
    log_audit(module='purchase_requests', action='update', record_id=pr.id,
              record_identifier=pr.pr_number, notes=f'Cancelled: {reason}')
    flash(f'Purchase Request "{pr.pr_number}" cancelled.', 'warning')
    return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/convert', methods=['POST'])
@login_required
def convert(id):
    """Approved PR -> a NEW draft Purchase Order (buyer adds vendor + prices).
    Mirror of quotations.accept -> draft SO."""
    pr = _get_pr_or_404(id)
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status != 'approved':
        flash('Only an approved Purchase Request can be converted to a Purchase Order.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    # Import inside the function to avoid an import cycle at module load.
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem, generate_po_number
    try:
        po = PurchaseOrder(
            po_number=generate_po_number(), branch_id=pr.branch_id,
            order_date=ph_now().date(), status='draft', vat_treatment='inclusive',
            notes='', purchase_request_id=pr.id, created_by_id=current_user.id)
        for li in pr.line_items:
            po.line_items.append(PurchaseOrderItem(
                line_number=li.line_number, product_id=li.product_id,
                description=li.description, quantity=li.quantity,
                unit_of_measure_id=li.unit_of_measure_id, uom_text=li.uom_text,
                unit_price=None, amount=Decimal('0'), vat_rate=Decimal('0')))
        po.calculate_totals()
        db.session.add(po); db.session.flush()      # get po.id
        pr.status = 'converted'
        pr.purchase_order_id = po.id
        db.session.commit()
        log_audit(module='purchase_requests', action='convert', record_id=pr.id,
                  record_identifier=pr.pr_number, notes=f'Converted -> {po.po_number}')
        flash(f'Purchase Request "{pr.pr_number}" converted to draft Purchase Order '
              f'"{po.po_number}". Add the vendor and prices.', 'success')
        return redirect(url_for('purchase_orders.view', id=po.id))
    except Exception as e:
        db.session.rollback()
        log_exception(e, severity='ERROR', module='purchase_requests.convert')
        flash('An error occurred converting the Purchase Request.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/print')
@login_required
def print_pr(id):
    pr = _get_pr_or_404(id)
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    return render_template('purchase_requests/print.html', pr=pr, company=company,
                           printed_at=ph_now())


# -- export routes -----------------------------------------------------------------

_EXPORT_COLUMNS = ['pr_number', 'request_date', 'reason', 'status']
_EXPORT_HEADERS = ['PR #', 'Request Date', 'Reason', 'Status']


@purchase_requests_bp.route('/purchase-requests/export/excel')
@login_required
def export_excel():
    from app.utils.export import export_to_excel
    rows = _filtered_pr_query(include_ids=True).order_by(PurchaseRequest.request_date.desc()).all()
    log_audit('purchase_requests', 'export_excel', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                           filename=f'purchase_requests_{timestamp}.xlsx',
                           title='Purchase Requests Report')


@purchase_requests_bp.route('/purchase-requests/export/csv')
@login_required
def export_csv_route():
    from app.utils.export import export_to_csv
    rows = _filtered_pr_query(include_ids=True).order_by(PurchaseRequest.request_date.desc()).all()
    log_audit('purchase_requests', 'export_csv', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                         filename=f'purchase_requests_{timestamp}.csv')
