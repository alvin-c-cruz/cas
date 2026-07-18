"""Fixed asset disposal (R-05 Slice 3): create/void, list."""
from decimal import Decimal
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.fixed_asset_disposal.forms import DisposalForm, VoidDisposalForm
from app.fixed_asset_disposal.models import FixedAssetDisposal
from app.fixed_asset_disposal.service import dispose_fixed_asset, void_fixed_asset_disposal
from app.fixed_assets.models import FixedAsset
from app.fixed_assets.services import leaf_accounts_by_type
from app.users.utils import get_accessible_branches

fixed_asset_disposal_bp = Blueprint('fixed_asset_disposal', __name__, template_folder='templates')


def _accountant_or_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can dispose fixed assets.', 'error')
            return redirect(url_for('fixed_asset_disposal.list_disposals'))
        return f(*args, **kwargs)
    return decorated


@fixed_asset_disposal_bp.route('/fixed-asset-disposal/new/<int:fixed_asset_id>',
                               methods=['GET', 'POST'])
@login_required
@_accountant_or_admin_required
def new_disposal(fixed_asset_id):
    asset = db.get_or_404(FixedAsset, fixed_asset_id)
    form = DisposalForm()
    form.proceeds_account_id.choices = [('', '-- None --')] + [
        (str(a.id), f'{a.code} — {a.name}') for a in leaf_accounts_by_type('Asset')]

    if form.validate_on_submit():
        proceeds_account_id = int(form.proceeds_account_id.data) if form.proceeds_account_id.data else None
        try:
            dispose_fixed_asset(
                fixed_asset_id=asset.id, disposal_date=form.disposal_date.data,
                disposal_type=form.disposal_type.data,
                proceeds_amount=form.proceeds_amount.data or Decimal('0'),
                proceeds_account_id=proceeds_account_id, user_id=current_user.id,
                notes=form.notes.data,
            )
            flash(f'Fixed asset "{asset.code}" disposed.', 'success')
            return redirect(url_for('fixed_asset_disposal.list_disposals'))
        except ValueError as e:
            flash(str(e), 'error')

    return render_template('fixed_asset_disposal/create.html', form=form, asset=asset)


@fixed_asset_disposal_bp.route('/fixed-asset-disposal')
@login_required
def list_disposals():
    accessible_ids = [b.id for b in get_accessible_branches(current_user)]
    disposals = FixedAssetDisposal.query.join(FixedAsset) \
        .filter(FixedAsset.branch_id.in_(accessible_ids)) \
        .order_by(FixedAssetDisposal.disposal_date.desc()).all()
    return render_template('fixed_asset_disposal/list.html', disposals=disposals,
                           void_form=VoidDisposalForm())


@fixed_asset_disposal_bp.route('/fixed-asset-disposal/<int:id>/void', methods=['POST'])
@login_required
@_accountant_or_admin_required
def void_disposal(id):
    disposal = db.get_or_404(FixedAssetDisposal, id)
    form = VoidDisposalForm()
    if not form.validate_on_submit():
        flash('A valid void date is required.', 'error')
        return redirect(url_for('fixed_asset_disposal.list_disposals'))
    try:
        void_fixed_asset_disposal(disposal, form.void_date.data, current_user.id)
        flash(f'Disposal for "{disposal.fixed_asset.code}" voided.', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('fixed_asset_disposal.list_disposals'))
