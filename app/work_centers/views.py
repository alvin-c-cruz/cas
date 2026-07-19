"""Work Center CRUD views (R-07 Discrete Track slice D1). Mirrors
units_of_measure's CRUD shape; branch handling mirrors bank_accounts
(session-derived, no branch picker field)."""
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_required, current_user

from app import db
from app.work_centers.models import WorkCenter
from app.work_centers.forms import WorkCenterForm
from app.audit.utils import log_create, log_update

work_centers_bp = Blueprint('work_centers', __name__, template_folder='templates')


def _can_manage():
    return current_user.has_full_access or current_user.role == 'accountant'


@work_centers_bp.route('/work-centers')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    centers = (WorkCenter.query.filter_by(branch_id=branch_id)
              .order_by(WorkCenter.code).all())
    return render_template('work_centers/list.html', centers=centers)


@work_centers_bp.route('/work-centers/create', methods=['GET', 'POST'])
@login_required
def create():
    if not _can_manage():
        flash('You do not have permission to manage work centers.', 'error')
        return redirect(url_for('work_centers.list'))
    form = WorkCenterForm()
    if form.validate_on_submit():
        wc = WorkCenter(
            branch_id=session.get('selected_branch_id'),
            code=form.code.data.strip(),
            name=form.name.data.strip(),
            hourly_rate=form.hourly_rate.data,
            is_active=(form.is_active.data == '1'),
            created_by_id=current_user.id,
        )
        db.session.add(wc)
        db.session.commit()
        log_create('work_centers', wc.id, wc.code, wc.to_dict())
        flash('Work center created.', 'success')
        return redirect(url_for('work_centers.list'))
    return render_template('work_centers/form.html', form=form, title='Create Work Center', center=None)


@work_centers_bp.route('/work-centers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not _can_manage():
        flash('You do not have permission to manage work centers.', 'error')
        return redirect(url_for('work_centers.list'))
    wc = db.get_or_404(WorkCenter, id)
    form = WorkCenterForm(obj=wc)
    if request.method == 'GET':
        form.is_active.data = '1' if wc.is_active else '0'
    if form.validate_on_submit():
        old = wc.to_dict()
        wc.code = form.code.data.strip()
        wc.name = form.name.data.strip()
        wc.hourly_rate = form.hourly_rate.data
        wc.is_active = (form.is_active.data == '1')
        db.session.commit()
        log_update('work_centers', wc.id, wc.code, old, wc.to_dict())
        flash('Work center updated.', 'success')
        return redirect(url_for('work_centers.list'))
    return render_template('work_centers/form.html', form=form, title='Edit Work Center', center=wc)
