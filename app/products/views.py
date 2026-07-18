"""Product / Item master (Maintenance). Mirrors the Vendor/UOM CRUD pattern."""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.products.models import Product
from app.products.forms import ProductForm
from app.utils.cache_helpers import (get_active_units, get_active_accounts, clear_product_cache,
                                     get_active_product_categories)
from app.audit.utils import log_create, log_update

products_bp = Blueprint('products', __name__, template_folder='templates')


def _populate_choices(form):
    """Populate FK select choices from cached active records."""
    units = get_active_units()
    accounts = get_active_accounts()
    form.default_unit_of_measure_id.choices = (
        [('', '— None —')] + [(str(u.id), f'{u.code} — {u.name}') for u in units]
    )
    form.default_account_id.choices = (
        [('', '— None —')] + [(str(a.id), f'{a.code} — {a.name}') for a in accounts]
    )
    form.category_id.choices = (
        [('', '— None —')] + [(str(c.id), f'{c.code} — {c.name}')
                              for c in get_active_product_categories()]
    )


def _int_or_none(v):
    """Convert a SelectField string value to int, or None for the blank sentinel."""
    return int(v) if v not in (None, '', 'None') else None


@products_bp.route('/products')
@login_required
def list():
    products = Product.query.order_by(Product.code).all()
    return render_template('products/list.html', products=products)


@products_bp.route('/products/create', methods=['GET', 'POST'])
@login_required
def create():
    # staff-or-above (mirrors customers.create): a quotation-delegated staff must be able to
    # inline-add a product from the quote line grid without holding the Products module
    # (BUG-QUOTE-DELEGATE-ADD-PRODUCT, owner directive 2026-07-11 full-parity with customers).
    # viewer stays blocked. products.create is EXEMPT_ENDPOINTS so the module gate lets it through.
    if current_user.role not in ('staff', 'accountant', 'chief_accountant', 'admin'):
        flash('You do not have permission to manage products.', 'error')
        return redirect(url_for('products.list'))
    form = ProductForm()
    _populate_choices(form)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if form.validate_on_submit():
        p = Product(
            code=form.code.data.strip(),
            name=form.name.data.strip(),
            description=(form.description.data or '').strip() or None,
            job_order_name=(form.job_order_name.data or '').strip() or None,
            default_unit_of_measure_id=_int_or_none(form.default_unit_of_measure_id.data),
            default_unit_price=form.default_unit_price.data,
            default_account_id=_int_or_none(form.default_account_id.data),
            category_id=_int_or_none(form.category_id.data),
            track_inventory=form.track_inventory.data,
            costing_method=(form.costing_method.data or None),
            standard_cost=form.standard_cost.data,
            reorder_level=form.reorder_level.data,
            is_active=(form.is_active.data == '1'),
            created_by_id=current_user.id,
        )
        db.session.add(p)
        db.session.commit()
        clear_product_cache()
        log_create('products', p.id, p.code, p.to_dict())
        if is_ajax:
            return jsonify(ok=True, product={
                'id': p.id, 'code': p.code, 'name': p.name,
                'label': f'{p.code} — {p.name}',
                'default_uom_id': p.default_unit_of_measure_id,
                'unit_price': float(p.default_unit_price or 0),
                'default_account_id': p.default_account_id,
            })
        flash('Product created.', 'success')
        return redirect(url_for('products.list'))
    if is_ajax and request.method == 'POST':
        errors = {f.name: f.errors[0] for f in form if f.errors}
        return jsonify(ok=False, errors=errors), 400
    return render_template('products/form.html', form=form, title='Create Product', product=None)


@products_bp.route('/products/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to manage products.', 'error')
        return redirect(url_for('products.list'))
    p = db.get_or_404(Product, id)
    form = ProductForm(obj=p)
    _populate_choices(form)
    if request.method == 'GET':
        form.is_active.data = '1' if p.is_active else '0'
        form.default_unit_of_measure_id.data = str(p.default_unit_of_measure_id or '')
        form.default_account_id.data = str(p.default_account_id or '')
        form.category_id.data = str(p.category_id or '')
        form.costing_method.data = p.costing_method or ''
    if form.validate_on_submit():
        old = p.to_dict()
        p.code = form.code.data.strip()
        p.name = form.name.data.strip()
        p.description = (form.description.data or '').strip() or None
        p.job_order_name = (form.job_order_name.data or '').strip() or None
        p.default_unit_of_measure_id = _int_or_none(form.default_unit_of_measure_id.data)
        p.default_unit_price = form.default_unit_price.data
        p.default_account_id = _int_or_none(form.default_account_id.data)
        p.category_id = _int_or_none(form.category_id.data)
        p.track_inventory = form.track_inventory.data
        p.costing_method = (form.costing_method.data or None)
        p.standard_cost = form.standard_cost.data
        p.reorder_level = form.reorder_level.data
        p.is_active = (form.is_active.data == '1')
        db.session.commit()
        clear_product_cache()
        log_update('products', p.id, p.code, old, p.to_dict())
        flash('Product updated.', 'success')
        return redirect(url_for('products.list'))
    return render_template('products/form.html', form=form, title='Edit Product', product=p)
