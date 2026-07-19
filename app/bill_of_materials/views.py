"""Bill of Materials CRUD views (R-07 Wave 0). Accountant/admin/chief-accountant
only -- same tier and reasoning as bank_reconciliation (a formula/routing
definition is a control activity, not routine data entry)."""
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app import db
from app.audit.utils import log_create, log_update, model_to_dict
from app.utils.cache_helpers import get_active_products, get_active_units
from app.utils.concurrency import claim_version, conflict_message, submitted_version
from app.bill_of_materials.models import BillOfMaterial
from app.bill_of_materials.forms import BillOfMaterialForm, _parse_and_attach_bom_lines
from app.bill_of_materials import service

bill_of_materials_bp = Blueprint('bill_of_materials', __name__, template_folder='templates')

_BOM_FIELDS = ['product_id', 'manufacturing_mode', 'is_active']


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


def _unclaimed_product_choices(exclude_bom_id=None):
    claimed_query = BillOfMaterial.query
    if exclude_bom_id is not None:
        claimed_query = claimed_query.filter(BillOfMaterial.id != exclude_bom_id)
    claimed = {b.product_id for b in claimed_query.all()}
    return [(p.id, f'{p.code} — {p.name}') for p in get_active_products() if p.id not in claimed]


@bill_of_materials_bp.route('/bill-of-materials/')
@login_required
@accountant_or_above_required
def list_boms():
    boms = BillOfMaterial.query.order_by(BillOfMaterial.id).all()
    return render_template('bill_of_materials/list.html', boms=boms)


@bill_of_materials_bp.route('/bill-of-materials/new', methods=['GET', 'POST'])
@login_required
@accountant_or_above_required
def new_bom():
    modes = service.available_manufacturing_modes()
    if not modes:
        flash('Enable Discrete or Process Manufacturing in Company Settings before '
              'creating a Bill of Materials.', 'error')
        return redirect(url_for('bill_of_materials.list_boms'))

    form = BillOfMaterialForm()
    form.product_id.choices = _unclaimed_product_choices()
    form.manufacturing_mode.choices = modes

    if request.method == 'POST' and form.validate_on_submit():
        try:
            bom = BillOfMaterial(product_id=form.product_id.data,
                                 manufacturing_mode=form.manufacturing_mode.data,
                                 created_by_id=current_user.id)
            _parse_and_attach_bom_lines(bom, request.form.get('lines', '[]'))
            db.session.add(bom)
            db.session.commit()
            log_create('bill_of_materials', bom.id, bom.product.code, model_to_dict(bom, _BOM_FIELDS))
            flash('Bill of Materials created.', 'success')
            return redirect(url_for('bill_of_materials.list_boms'))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')

    return render_template('bill_of_materials/form.html', form=form, bom=None,
                           units=[u.to_dict() for u in get_active_units()],
                           components=[p.to_dict() for p in get_active_products()],
                           line_items=[])


@bill_of_materials_bp.route('/bill-of-materials/<int:bom_id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_above_required
def edit_bom(bom_id):
    bom = db.get_or_404(BillOfMaterial, bom_id)
    modes = service.available_manufacturing_modes()
    form = BillOfMaterialForm(obj=bom)
    form.product_id.choices = [(bom.product_id, f'{bom.product.code} — {bom.product.name}')]
    form.manufacturing_mode.choices = modes or [(bom.manufacturing_mode, bom.manufacturing_mode)]

    if request.method == 'POST' and form.validate_on_submit():
        if not claim_version(BillOfMaterial, bom.id, submitted_version()):
            db.session.rollback()
            flash(conflict_message('bill_of_materials', bom.id), 'error')
            return render_template('bill_of_materials/form.html', form=form, bom=bom,
                                   units=[u.to_dict() for u in get_active_units()],
                                   components=[p.to_dict() for p in get_active_products()],
                                   line_items=[line.to_dict() for line in bom.lines])
        try:
            old_values = model_to_dict(bom, _BOM_FIELDS)
            bom.manufacturing_mode = form.manufacturing_mode.data
            bom.lines = []
            _parse_and_attach_bom_lines(bom, request.form.get('lines', '[]'))
            db.session.commit()
            log_update('bill_of_materials', bom.id, bom.product.code, old_values,
                       model_to_dict(bom, _BOM_FIELDS))
            flash('Bill of Materials updated.', 'success')
            return redirect(url_for('bill_of_materials.list_boms'))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')

    return render_template('bill_of_materials/form.html', form=form, bom=bom,
                           units=[u.to_dict() for u in get_active_units()],
                           components=[p.to_dict() for p in get_active_products()],
                           line_items=[line.to_dict() for line in bom.lines])


@bill_of_materials_bp.route('/bill-of-materials/<int:bom_id>/toggle-active', methods=['POST'])
@login_required
@accountant_or_above_required
def toggle_active(bom_id):
    bom = db.get_or_404(BillOfMaterial, bom_id)
    old_values = model_to_dict(bom, _BOM_FIELDS)
    bom.is_active = not bom.is_active
    db.session.commit()
    log_update('bill_of_materials', bom.id, bom.product.code, old_values,
               model_to_dict(bom, _BOM_FIELDS))
    return redirect(url_for('bill_of_materials.list_boms'))
