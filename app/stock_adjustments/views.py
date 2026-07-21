"""Stock Adjustments blueprint (R-03 slice 2a-i).

Skeleton for Task 7: module gate + a list-only `index` route. Create/edit/
approve/void views and their real templates land in Task 8.
"""
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from app.users.module_access import module_enabled

stock_adjustments_bp = Blueprint('stock_adjustments', __name__,
                                 url_prefix='/stock-adjustments',
                                 template_folder='templates')


def _guard():
    if not module_enabled('stock_adjustments'):
        flash('The Stock Adjustments module is not enabled.', 'error')
        return redirect(url_for('dashboard.index'))
    return None


@stock_adjustments_bp.route('/')
@login_required
def index():
    blocked = _guard()
    if blocked:
        return blocked
    from app.stock_adjustments.models import StockAdjustment
    from app.users.utils import get_accessible_branches
    branch_ids = [b.id for b in get_accessible_branches(current_user)]
    adjustments = (StockAdjustment.query.filter(StockAdjustment.branch_id.in_(branch_ids))
                   .order_by(StockAdjustment.id.desc()).all())
    return render_template('stock_adjustments/list.html', adjustments=adjustments)
