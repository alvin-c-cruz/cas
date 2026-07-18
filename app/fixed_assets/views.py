"""Fixed Asset register (R-05 Slice 1): AssetCategory + FixedAsset CRUD, the
tagging flow, and the opening-asset flow."""
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.accounts.models import Account
from app.fixed_assets.models import AssetCategory
from app.fixed_assets.forms import AssetCategoryForm, FixedAssetForm
from app.fixed_assets.services import (
    FixedAssetTagError, get_taggable_line, create_fixed_asset, leaf_accounts_by_type,
)
from app.utils.cache_helpers import clear_asset_category_cache, get_active_asset_categories
from app.users.utils import get_accessible_branches
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


# ---- Opening assets --------------------------------------------------------

def _populate_common_choices(form):
    form.branch_id.choices = [(b.id, b.name) for b in get_accessible_branches(current_user)]
    form.category_id.choices = [('', '-- None --')] + [
        (str(c.id), c.name) for c in get_active_asset_categories()]
    form.accumulated_depreciation_account_id.choices = [
        (a.id, f'{a.code} — {a.name}') for a in leaf_accounts_by_type('Asset')]
    form.depreciation_expense_account_id.choices = [
        (a.id, f'{a.code} — {a.name}') for a in leaf_accounts_by_type('Expense')]


@fixed_assets_bp.route('/fixed-assets/new-opening', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def new_opening():
    form = FixedAssetForm()
    _populate_common_choices(form)
    form.cost_account_id.choices = [(a.id, f'{a.code} — {a.name}')
                                    for a in leaf_accounts_by_type('Asset')]

    if form.validate_on_submit():
        asset = create_fixed_asset(
            branch_id=form.branch_id.data, code=form.code.data.strip(),
            name=form.name.data.strip(),
            category_id=(int(form.category_id.data) if form.category_id.data else None),
            acquisition_source_type='opening', acquisition_source_id=None,
            acquisition_source_line_id=None, acquisition_date=form.acquisition_date.data,
            acquisition_cost=form.acquisition_cost.data, cost_account_id=form.cost_account_id.data,
            accumulated_depreciation_account_id=form.accumulated_depreciation_account_id.data,
            depreciation_expense_account_id=form.depreciation_expense_account_id.data,
            depreciation_method=form.depreciation_method.data,
            useful_life_months=form.useful_life_months.data,
            declining_balance_rate=form.declining_balance_rate.data,
            total_estimated_units=form.total_estimated_units.data,
            salvage_value=form.salvage_value.data or 0,
            opening_accumulated_depreciation=form.opening_accumulated_depreciation.data or 0,
            created_by_id=current_user.id,
        )
        log_create('fixed_assets', asset.id, asset.code, asset.to_dict(),
                  notes='Opening asset (pre-CAS acquisition)')
        flash(f'Opening asset "{asset.code}" created.', 'success')
        return redirect(url_for('fixed_assets.list'))

    return render_template('fixed_assets/form.html', form=form, title='Add Opening Asset',
                           asset=None, is_opening=True, readonly_code=False,
                           readonly_acquisition=False)


# ---- Tag flow ---------------------------------------------------------------

@fixed_assets_bp.route('/fixed-assets/tag/<source_type>/<int:source_id>/<int:source_line_id>',
                       methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def tag(source_type, source_id, source_line_id):
    try:
        line, cost_account_id, amount = get_taggable_line(source_type, source_id, source_line_id)
    except FixedAssetTagError as e:
        flash(str(e), 'error')
        return redirect(request.referrer or url_for('fixed_assets.list'))

    cost_account = db.session.get(Account, cost_account_id)
    form = FixedAssetForm()
    _populate_common_choices(form)
    form.cost_account_id.choices = [(cost_account_id,
                                     f'{cost_account.code} — {cost_account.name}')]

    if request.method == 'GET':
        form.acquisition_cost.data = amount
        form.cost_account_id.data = cost_account_id

    if form.validate_on_submit():
        asset = create_fixed_asset(
            branch_id=form.branch_id.data, code=form.code.data.strip(),
            name=form.name.data.strip(),
            category_id=(int(form.category_id.data) if form.category_id.data else None),
            acquisition_source_type=source_type, acquisition_source_id=source_id,
            acquisition_source_line_id=source_line_id, acquisition_date=form.acquisition_date.data,
            acquisition_cost=amount, cost_account_id=cost_account_id,
            accumulated_depreciation_account_id=form.accumulated_depreciation_account_id.data,
            depreciation_expense_account_id=form.depreciation_expense_account_id.data,
            depreciation_method=form.depreciation_method.data,
            useful_life_months=form.useful_life_months.data,
            declining_balance_rate=form.declining_balance_rate.data,
            total_estimated_units=form.total_estimated_units.data,
            salvage_value=form.salvage_value.data or 0,
            opening_accumulated_depreciation=0, created_by_id=current_user.id,
        )
        log_create('fixed_assets', asset.id, asset.code, asset.to_dict(),
                  notes=f'Capitalized from {source_type} #{source_id} line #{source_line_id}')
        flash(f'Fixed asset "{asset.code}" created.', 'success')
        return redirect(url_for('fixed_assets.list'))

    return render_template('fixed_assets/form.html', form=form,
                           title='Capitalize as Fixed Asset', asset=None, is_opening=False,
                           readonly_code=False, readonly_acquisition=True)
