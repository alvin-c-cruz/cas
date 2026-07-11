"""Receiving Report views -- goods received against an approved Purchase Order.
Buy-side mirror of app/delivery_receipts/views.py. Operational only: posts NO journal entry.
CRUD lands in Task 4, lifecycle in Task 5."""
from flask import Blueprint, render_template, request, session
from flask_login import login_required

from app.receiving_reports.models import ReceivingReport

receiving_reports_bp = Blueprint('receiving_reports', __name__, template_folder='templates')

VALID_RR_STATUSES = {'draft', 'approved', 'billed', 'cancelled'}


@receiving_reports_bp.route('/receiving-reports')
@login_required
def list_rr():
    branch_id = session.get('selected_branch_id')
    query = ReceivingReport.query.filter_by(branch_id=branch_id)
    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_RR_STATUSES:
        query = query.filter_by(status=status_filter)
    receipts = query.order_by(ReceivingReport.receipt_date.desc(),
                              ReceivingReport.id.desc()).all()
    return render_template('receiving_reports/list.html', receipts=receipts,
                           status_filter=status_filter)
