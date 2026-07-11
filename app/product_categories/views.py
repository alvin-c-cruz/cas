"""Product Category master (Maintenance). Mirrors the Units of Measure CRUD pattern."""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.product_categories.models import ProductCategory
from app.product_categories.forms import ProductCategoryForm
from app.utils.cache_helpers import clear_product_category_cache
from app.audit.utils import log_create, log_update

product_categories_bp = Blueprint('product_categories', __name__, template_folder='templates')


@product_categories_bp.route('/product-categories')
@login_required
def list():
    categories = ProductCategory.query.order_by(ProductCategory.code).all()
    return render_template('product_categories/list.html', categories=categories)


@product_categories_bp.route('/product-categories/create', methods=['GET', 'POST'])
@login_required
def create():
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to manage product categories.', 'error')
        return redirect(url_for('product_categories.list'))
    form = ProductCategoryForm()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if form.validate_on_submit():
        c = ProductCategory(
            code=form.code.data.strip(),
            name=form.name.data.strip(),
            is_active=(form.is_active.data == '1'),
            created_by_id=current_user.id,
        )
        db.session.add(c)
        db.session.commit()
        clear_product_category_cache()
        log_create('product_categories', c.id, c.code, c.to_dict())
        if is_ajax:
            return jsonify(ok=True, category={'id': c.id, 'code': c.code, 'name': c.name})
        flash('Product category created.', 'success')
        return redirect(url_for('product_categories.list'))
    if is_ajax and request.method == 'POST':
        errors = {f.name: f.errors[0] for f in form if f.errors}
        return jsonify(ok=False, errors=errors), 400
    return render_template('product_categories/form.html', form=form,
                           title='Create Product Category', category=None)


@product_categories_bp.route('/product-categories/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to manage product categories.', 'error')
        return redirect(url_for('product_categories.list'))
    c = db.get_or_404(ProductCategory, id)
    form = ProductCategoryForm(obj=c)
    if request.method == 'GET':
        form.is_active.data = '1' if c.is_active else '0'
    if form.validate_on_submit():
        old = c.to_dict()
        c.code = form.code.data.strip()
        c.name = form.name.data.strip()
        c.is_active = (form.is_active.data == '1')
        db.session.commit()
        clear_product_category_cache()
        log_update('product_categories', c.id, c.code, old, c.to_dict())
        flash('Product category updated.', 'success')
        return redirect(url_for('product_categories.list'))
    return render_template('product_categories/form.html', form=form,
                           title='Edit Product Category', category=c)
