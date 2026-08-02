"""Production Run views (R-07 Process Track slice P2).

Branch handling is session-derived. The by-id fetch is branch-scoped, same as P1 --
work_centers/bank_accounts fetch by bare id and thereby expose another branch's
record by URL (BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED); not reproduced here.
"""
from decimal import Decimal

from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_required, current_user

from app import db
from app.audit.utils import log_create, log_update
from app.bill_of_materials.models import BillOfMaterial
from app.manufacturing_departments.models import ManufacturingDepartment
from app.production_runs.costing import compute_run_costing
from app.production_runs.forms import (ProductionRunForm, ProductionRunPeriodForm,
                                       generate_run_number)
from app.production_runs.models import ProductionRun
from app.production_runs.service import (carry_beginning_wip, issue_material,
                                        snapshot_materials)

production_runs_bp = Blueprint('production_runs', __name__, template_folder='templates')


def _can_manage():
    return current_user.has_full_access or current_user.role == 'accountant'


def _get_scoped(id):
    return (ProductionRun.query
            .filter_by(id=id, branch_id=session.get('selected_branch_id'))
            .first_or_404())


def _populate_choices(form, branch_id):
    form.bom_id.choices = [
        (b.id, f'{b.product.code} - {b.product.name}')
        for b in BillOfMaterial.query.filter_by(is_active=True).all() if b.product]
    form.department_id.choices = [
        (d.id, f'{d.code} - {d.name}')
        for d in ManufacturingDepartment.query
        .filter_by(branch_id=branch_id, is_active=True)
        .order_by(ManufacturingDepartment.code).all()]


@production_runs_bp.route('/production-runs')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    runs = (ProductionRun.query.filter_by(branch_id=branch_id)
            .order_by(ProductionRun.run_number.desc()).all())
    return render_template('production_runs/list.html', runs=runs)


@production_runs_bp.route('/production-runs/create', methods=['GET', 'POST'])
@login_required
def create():
    if not _can_manage():
        flash('You do not have permission to manage production runs.', 'error')
        return redirect(url_for('production_runs.list'))
    branch_id = session.get('selected_branch_id')
    form = ProductionRunForm()
    _populate_choices(form, branch_id)
    if form.validate_on_submit():
        run = ProductionRun(
            run_number=generate_run_number(),
            bom_id=form.bom_id.data,
            department_id=form.department_id.data,
            branch_id=branch_id,
            period_start=form.period_start.data,
            period_end=form.period_end.data,
            units_started=form.units_started.data,
            created_by_id=current_user.id,
        )
        db.session.add(run)
        db.session.flush()          # need run.bom for the snapshot
        # Pull the predecessor period's leftover WIP forward before anything else --
        # it is part of this period's cost pool, so it must be stamped on the run
        # itself, not recomputed on every page view.
        carry_beginning_wip(run)
        try:
            snapshot_materials(run)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return render_template('production_runs/form.html', form=form,
                                   title='Open Production Run')
        db.session.commit()
        log_create('production_runs', run.id, run.run_number, run.to_dict())
        flash(f'Production Run {run.run_number} opened.', 'success')
        return redirect(url_for('production_runs.detail', id=run.id))
    return render_template('production_runs/form.html', form=form,
                           title='Open Production Run')


@production_runs_bp.route('/production-runs/<int:id>')
@login_required
def detail(id):
    run = _get_scoped(id)
    period_form = ProductionRunPeriodForm(obj=run)
    return render_template('production_runs/detail.html', run=run,
                           period_form=period_form, costing=compute_run_costing(run))


@production_runs_bp.route('/production-runs/<int:id>/period', methods=['POST'])
@login_required
def period_results(id):
    """Record the period's completed/ending-WIP units and conversion cost (R-07 P3)."""
    if not _can_manage():
        flash('You do not have permission to manage production runs.', 'error')
        return redirect(url_for('production_runs.list'))
    run = _get_scoped(id)
    form = ProductionRunPeriodForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for err in errors:
                flash(err, 'error')
        return redirect(url_for('production_runs.detail', id=run.id))
    old = run.to_dict()
    if form.units_completed_and_transferred.data is not None:
        run.units_completed_and_transferred = form.units_completed_and_transferred.data
    if form.units_ending_wip.data is not None:
        run.units_ending_wip = form.units_ending_wip.data
    if form.ending_wip_pct_complete.data is not None:
        run.ending_wip_pct_complete = form.ending_wip_pct_complete.data
    if form.conversion_cost.data is not None:
        run.conversion_cost = form.conversion_cost.data
    db.session.commit()
    log_update('production_runs', run.id, run.run_number, old, run.to_dict())
    flash('Period results saved.', 'success')
    return redirect(url_for('production_runs.detail', id=run.id))


@production_runs_bp.route('/production-runs/<int:id>/materials/<int:material_id>/issue',
                          methods=['POST'])
@login_required
def issue(id, material_id):
    if not _can_manage():
        flash('You do not have permission to manage production runs.', 'error')
        return redirect(url_for('production_runs.list'))
    run = _get_scoped(id)
    material = next((m for m in run.materials if m.id == material_id), None)
    if material is None:
        flash('That component is not part of this Production Run.', 'error')
        return redirect(url_for('production_runs.detail', id=run.id))
    old = run.to_dict()
    try:
        issue_material(material, Decimal(request.form.get('quantity') or '0'), current_user)
    except (ValueError, ArithmeticError) as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('production_runs.detail', id=run.id))
    db.session.commit()
    log_update('production_runs', run.id, run.run_number, old, run.to_dict())
    flash(f'Issued {request.form.get("quantity")} of '
          f'"{material.component_product.code}".', 'success')
    return redirect(url_for('production_runs.detail', id=run.id))
