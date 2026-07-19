"""Work Order CRUD + release/cancel views (R-07 Discrete Track slice D2).
Accountant/admin/chief-accountant only, same tier as bill_of_materials --
releasing a job is a control activity, not routine entry."""
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, abort
from flask_login import login_required, current_user

from app import db
from app.audit.utils import log_create, log_update
from app.utils.concurrency import claim_version, conflict_message, submitted_version
from app.utils import ph_now
from app.work_orders.models import WorkOrder
from app.work_orders.forms import WorkOrderForm, generate_wo_number
from app.work_orders.service import release_work_order
from app.bill_of_materials.models import BillOfMaterial

work_orders_bp = Blueprint('work_orders', __name__, template_folder='templates')


def accountant_or_above_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def _active_bom_choices():
    return [(b.id, f'{b.product.code} — {b.product.name} ({b.manufacturing_mode})')
            for b in BillOfMaterial.query.filter_by(is_active=True).all()]


@work_orders_bp.route('/work-orders')
@login_required
@accountant_or_above_required
def list():
    branch_id = session.get('selected_branch_id')
    wos = WorkOrder.query.filter_by(branch_id=branch_id).order_by(WorkOrder.id.desc()).all()
    return render_template('work_orders/list.html', wos=wos)


@work_orders_bp.route('/work-orders/create', methods=['GET', 'POST'])
@login_required
@accountant_or_above_required
def create():
    form = WorkOrderForm()
    form.bom_id.choices = _active_bom_choices()
    if not form.bom_id.choices:
        flash('No active Bills of Materials available. Create one first.', 'error')
        return redirect(url_for('bill_of_materials.list_boms'))

    if form.validate_on_submit():
        wo = WorkOrder(wo_number=generate_wo_number(), bom_id=form.bom_id.data,
                       branch_id=session.get('selected_branch_id'),
                       qty_to_produce=form.qty_to_produce.data,
                       planned_start_date=form.planned_start_date.data,
                       planned_end_date=form.planned_end_date.data,
                       created_by_id=current_user.id)
        db.session.add(wo)
        db.session.commit()
        log_create('work_orders', wo.id, wo.wo_number,
                  {'bom_id': wo.bom_id, 'qty_to_produce': float(wo.qty_to_produce)})
        flash(f'Work Order "{wo.wo_number}" created (draft).', 'success')
        return redirect(url_for('work_orders.view', id=wo.id))

    return render_template('work_orders/form.html', form=form, wo=None)


@work_orders_bp.route('/work-orders/<int:id>')
@login_required
@accountant_or_above_required
def view(id):
    wo = db.get_or_404(WorkOrder, id)
    if wo.branch_id != session.get('selected_branch_id'):
        abort(404)
    return render_template('work_orders/view.html', wo=wo)


@work_orders_bp.route('/work-orders/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_above_required
def edit(id):
    wo = db.get_or_404(WorkOrder, id)
    if wo.branch_id != session.get('selected_branch_id'):
        abort(404)
    if wo.status != 'draft':
        flash('Only a draft Work Order can be edited.', 'error')
        return redirect(url_for('work_orders.view', id=id))
    form = WorkOrderForm(obj=wo)
    form.bom_id.choices = _active_bom_choices()
    if form.validate_on_submit():
        if not claim_version(WorkOrder, wo.id, submitted_version()):
            db.session.rollback()
            flash(conflict_message('work_orders', wo.id), 'error')
            return render_template('work_orders/form.html', form=form, wo=wo)
        wo.bom_id = form.bom_id.data
        wo.qty_to_produce = form.qty_to_produce.data
        wo.planned_start_date = form.planned_start_date.data
        wo.planned_end_date = form.planned_end_date.data
        db.session.commit()
        log_update('work_orders', wo.id, wo.wo_number, {}, {'qty_to_produce': float(wo.qty_to_produce)})
        flash(f'Work Order "{wo.wo_number}" updated.', 'success')
        return redirect(url_for('work_orders.view', id=id))
    return render_template('work_orders/form.html', form=form, wo=wo)


@work_orders_bp.route('/work-orders/<int:id>/release', methods=['POST'])
@login_required
@accountant_or_above_required
def release(id):
    wo = db.get_or_404(WorkOrder, id)
    if wo.branch_id != session.get('selected_branch_id'):
        abort(404)
    try:
        release_work_order(wo, current_user)
        db.session.commit()
        log_update('work_orders', wo.id, wo.wo_number, {'status': 'draft'}, {'status': 'released'})
        flash(f'Work Order "{wo.wo_number}" released.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    return redirect(url_for('work_orders.view', id=id))


@work_orders_bp.route('/work-orders/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_above_required
def cancel(id):
    wo = db.get_or_404(WorkOrder, id)
    if wo.branch_id != session.get('selected_branch_id'):
        abort(404)
    if wo.status in ('completed', 'cancelled'):
        flash('This Work Order can no longer be cancelled.', 'error')
        return redirect(url_for('work_orders.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('work_orders.view', id=id))
    wo.status = 'cancelled'; wo.cancelled_by_id = current_user.id; wo.cancelled_at = ph_now()
    wo.cancel_reason = reason
    db.session.commit()
    log_update('work_orders', wo.id, wo.wo_number, {}, {'status': 'cancelled', 'reason': reason})
    flash(f'Work Order "{wo.wo_number}" cancelled.', 'warning')
    return redirect(url_for('work_orders.view', id=id))
