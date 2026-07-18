"""Fixed Asset register (R-05 Slice 1): AssetCategory + FixedAsset CRUD, the
tagging flow, and the opening-asset flow."""
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.fixed_assets.models import AssetCategory
from app.fixed_assets.forms import AssetCategoryForm
from app.utils.cache_helpers import clear_asset_category_cache
from app.audit.utils import log_create, log_update

fixed_assets_bp = Blueprint('fixed_assets', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Category/asset maintenance -- accountant or admin only."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('You do not have permission to manage Fixed Assets.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


# ---- Asset Categories ------------------------------------------------------

@fixed_assets_bp.route('/fixed-assets/categories')
@login_required
def category_list():
    categories = AssetCategory.query.order_by(AssetCategory.name).all()
    return render_template('fixed_assets/categories/list.html', categories=categories)


@fixed_assets_bp.route('/fixed-assets/categories/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def category_create():
    form = AssetCategoryForm()
    if form.validate_on_submit():
        cat = AssetCategory(
            name=form.name.data.strip(),
            default_useful_life_months=form.default_useful_life_months.data,
            default_depreciation_method=form.default_depreciation_method.data or None,
            is_active=(form.is_active.data == '1'),
            created_by_id=current_user.id,
        )
        db.session.add(cat)
        db.session.commit()
        clear_asset_category_cache()
        log_create('asset_categories', cat.id, cat.name, cat.to_dict())
        flash('Asset category created.', 'success')
        return redirect(url_for('fixed_assets.category_list'))
    return render_template('fixed_assets/categories/form.html', form=form,
                           title='Create Asset Category', category=None)


@fixed_assets_bp.route('/fixed-assets/categories/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def category_edit(id):
    cat = db.get_or_404(AssetCategory, id)
    form = AssetCategoryForm(obj=cat)
    if request.method == 'GET':
        form.is_active.data = '1' if cat.is_active else '0'
    if form.validate_on_submit():
        old = cat.to_dict()
        cat.name = form.name.data.strip()
        cat.default_useful_life_months = form.default_useful_life_months.data
        cat.default_depreciation_method = form.default_depreciation_method.data or None
        cat.is_active = (form.is_active.data == '1')
        db.session.commit()
        clear_asset_category_cache()
        log_update('asset_categories', cat.id, cat.name, old, cat.to_dict())
        flash('Asset category updated.', 'success')
        return redirect(url_for('fixed_assets.category_list'))
    return render_template('fixed_assets/categories/form.html', form=form,
                           title='Edit Asset Category', category=cat)
