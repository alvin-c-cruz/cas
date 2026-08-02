"""Manufacturing Department CRUD views (R-07 Process Track slice P1). Mirrors
work_centers' CRUD shape; branch handling is session-derived (no branch picker field).

ONE deliberate divergence from work_centers: `_get_scoped()` filters the by-id lookup
on the selected branch. work_centers and bank_accounts both use a bare
`db.get_or_404(Model, id)`, which hands back another branch's record to anyone who
types its URL -- logged as BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED. This
slice does not fix those; it declines to reproduce the defect.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_required, current_user

from app import db
from app.manufacturing_departments.models import ManufacturingDepartment
from app.manufacturing_departments.forms import ManufacturingDepartmentForm
from app.audit.utils import log_create, log_update

manufacturing_departments_bp = Blueprint('manufacturing_departments', __name__,
                                         template_folder='templates')


def _can_manage():
    return current_user.has_full_access or current_user.role == 'accountant'


def _get_scoped(id):
    """Fetch by id WITHIN the selected branch -- 404 for another branch's record."""
    return (ManufacturingDepartment.query
            .filter_by(id=id, branch_id=session.get('selected_branch_id'))
            .first_or_404())


@manufacturing_departments_bp.route('/manufacturing-departments')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    departments = (ManufacturingDepartment.query.filter_by(branch_id=branch_id)
                   .order_by(ManufacturingDepartment.code).all())
    return render_template('manufacturing_departments/list.html', departments=departments)


@manufacturing_departments_bp.route('/manufacturing-departments/create', methods=['GET', 'POST'])
@login_required
def create():
    if not _can_manage():
        flash('You do not have permission to manage manufacturing departments.', 'error')
        return redirect(url_for('manufacturing_departments.list'))
    form = ManufacturingDepartmentForm()
    if form.validate_on_submit():
        dept = ManufacturingDepartment(
            branch_id=session.get('selected_branch_id'),
            code=form.code.data.strip(),
            name=form.name.data.strip(),
            is_active=(form.is_active.data == '1'),
            created_by_id=current_user.id,
        )
        db.session.add(dept)
        db.session.commit()
        log_create('manufacturing_departments', dept.id, dept.code, dept.to_dict())
        flash('Department created.', 'success')
        return redirect(url_for('manufacturing_departments.list'))
    return render_template('manufacturing_departments/form.html', form=form,
                           title='Create Department', department=None)


@manufacturing_departments_bp.route('/manufacturing-departments/<int:id>/edit',
                                    methods=['GET', 'POST'])
@login_required
def edit(id):
    if not _can_manage():
        flash('You do not have permission to manage manufacturing departments.', 'error')
        return redirect(url_for('manufacturing_departments.list'))
    dept = _get_scoped(id)
    form = ManufacturingDepartmentForm(obj=dept)
    if request.method == 'GET':
        form.is_active.data = '1' if dept.is_active else '0'
    if form.validate_on_submit():
        old = dept.to_dict()
        dept.code = form.code.data.strip()
        dept.name = form.name.data.strip()
        dept.is_active = (form.is_active.data == '1')
        db.session.commit()
        log_update('manufacturing_departments', dept.id, dept.code, old, dept.to_dict())
        flash('Department updated.', 'success')
        return redirect(url_for('manufacturing_departments.list'))
    return render_template('manufacturing_departments/form.html', form=form,
                           title='Edit Department', department=dept)
