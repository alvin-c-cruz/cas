"""Units of Measure master (Maintenance). Mirrors the Vendor CRUD pattern."""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.units_of_measure.models import UnitOfMeasure
from app.units_of_measure.forms import UnitOfMeasureForm
from app.utils.cache_helpers import clear_uom_cache
from app.audit.utils import log_create, log_update

units_of_measure_bp = Blueprint('units_of_measure', __name__, template_folder='templates')


@units_of_measure_bp.route('/units-of-measure')
@login_required
def list():
    units = UnitOfMeasure.query.order_by(UnitOfMeasure.code).all()
    return render_template('units_of_measure/list.html', units=units)


@units_of_measure_bp.route('/units-of-measure/create', methods=['GET', 'POST'])
@login_required
def create():
    form = UnitOfMeasureForm()
    if form.validate_on_submit():
        u = UnitOfMeasure(
            code=form.code.data.strip(),
            name=form.name.data.strip(),
            is_active=(form.is_active.data == '1'),
            created_by_id=current_user.id,
        )
        db.session.add(u)
        db.session.commit()
        clear_uom_cache()
        log_create('units_of_measure', u.id, u.code, u.to_dict())
        flash('Unit of measure created.', 'success')
        return redirect(url_for('units_of_measure.list'))
    return render_template('units_of_measure/form.html', form=form, title='Create Unit of Measure', unit=None)


@units_of_measure_bp.route('/units-of-measure/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    u = db.get_or_404(UnitOfMeasure, id)
    form = UnitOfMeasureForm(obj=u)
    if request.method == 'GET':
        form.is_active.data = '1' if u.is_active else '0'
    if form.validate_on_submit():
        old = u.to_dict()
        u.code = form.code.data.strip()
        u.name = form.name.data.strip()
        u.is_active = (form.is_active.data == '1')
        db.session.commit()
        clear_uom_cache()
        log_update('units_of_measure', u.id, u.code, old, u.to_dict())
        flash('Unit of measure updated.', 'success')
        return redirect(url_for('units_of_measure.list'))
    return render_template('units_of_measure/form.html', form=form, title='Edit Unit of Measure', unit=u)
