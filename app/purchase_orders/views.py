"""Purchase Order views — buy-side mirror of app/sales_orders/views.py.

Operational document: posts NO journal entry. Gated by the `purchase_orders` optional module
(see app/users/module_access.py). CRUD + create form land in Task 4; lifecycle in Task 5.
"""
from flask import Blueprint, render_template, session
from flask_login import login_required

from app.purchase_orders.models import PurchaseOrder

purchase_orders_bp = Blueprint('purchase_orders', __name__, template_folder='templates')


@purchase_orders_bp.route('/purchase-orders')
@login_required
def list_po():
    branch_id = session.get('selected_branch_id')
    orders = (PurchaseOrder.query.filter_by(branch_id=branch_id)
              .order_by(PurchaseOrder.id.desc()).all())
    return render_template('purchase_orders/list.html', orders=orders)
