"""Purchase Request views -- a thin requisition that converts to a draft PO on approval.
Mirror of app/quotations/views.py. Operational only: posts NO journal entry.
CRUD lands in Task 4; lifecycle + convert in Task 5."""
from flask import Blueprint, render_template, request, session
from flask_login import login_required

from app.purchase_requests.models import PurchaseRequest

purchase_requests_bp = Blueprint('purchase_requests', __name__, template_folder='templates')

VALID_PR_STATUSES = {'draft', 'submitted', 'approved', 'rejected', 'converted', 'cancelled'}


@purchase_requests_bp.route('/purchase-requests')
@login_required
def list_pr():
    branch_id = session.get('selected_branch_id')
    query = PurchaseRequest.query.filter_by(branch_id=branch_id)
    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_PR_STATUSES:
        query = query.filter_by(status=status_filter)
    requests_ = query.order_by(PurchaseRequest.request_date.desc(),
                               PurchaseRequest.id.desc()).all()
    return render_template('purchase_requests/list.html', requests=requests_,
                           status_filter=status_filter)
