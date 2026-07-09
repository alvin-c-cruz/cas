"""Delivery Receipt views -- deliveries against a confirmed Sales Order. Operational only."""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, abort
from flask_login import login_required, current_user
from app import db
from app.delivery_receipts.models import DeliveryReceipt

delivery_receipts_bp = Blueprint('delivery_receipts', __name__, template_folder='templates')

VALID_DR_STATUSES = {'draft', 'approved', 'delivered', 'billed', 'cancelled'}


@delivery_receipts_bp.route('/delivery-receipts')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    query = DeliveryReceipt.query.filter_by(branch_id=branch_id)
    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_DR_STATUSES:
        query = query.filter_by(status=status_filter)
    receipts = query.order_by(DeliveryReceipt.delivery_date.desc(),
                              DeliveryReceipt.id.desc()).all()
    return render_template('delivery_receipts/list.html', receipts=receipts,
                           status_filter=status_filter)
