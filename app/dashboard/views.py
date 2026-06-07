from flask import Blueprint, render_template, redirect, url_for, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app.accounts.approval_models import AccountChangeRequest
from app.vat_categories.models import VATCategoryChangeRequest
from app.withholding_tax.models import WithholdingTaxChangeRequest
from app.dashboard.dashboard_data import (
    get_revenue_stats, get_expense_stats,
    get_receivables_stats, get_payables_stats,
    get_top_customers, get_top_vendors,
    get_monthly_revenue_trend, get_expense_breakdown
)

dashboard_bp = Blueprint('dashboard', __name__, template_folder='templates')

@dashboard_bp.route('/')
@login_required
def index():
    """Redirect to dashboard"""
    return redirect(url_for('dashboard.home'))

@dashboard_bp.route('/dashboard')
@login_required
def home():
    """Main dashboard page with real business metrics"""
    from flask import session, request

    # Get "as of" date from query parameter or default to today
    today = datetime.now().date()
    as_of_date_str = request.args.get('as_of_date')

    if as_of_date_str:
        try:
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d').date()
            # Allow any date - past, present, or future
        except ValueError:
            as_of_date = today
    else:
        as_of_date = today

    # Extract year and month from the as_of_date
    current_year = as_of_date.year
    current_month = as_of_date.month

    # Get current branch from session
    current_branch_id = session.get('selected_branch_id')

    # If no branch selected, try to get user's first assigned branch
    if not current_branch_id and current_user.branches.count() > 0:
        first_branch = current_user.branches.first()
        current_branch_id = first_branch.id
        session['selected_branch_id'] = current_branch_id

    # Get real financial statistics (filtered by current branch and as_of_date)
    revenue_stats = get_revenue_stats(current_year, current_month, branch_id=current_branch_id, as_of_date=as_of_date)
    expense_stats = get_expense_stats(current_year, current_month, branch_id=current_branch_id, as_of_date=as_of_date)
    receivables_stats = get_receivables_stats(as_of_date=as_of_date)
    payables_stats = get_payables_stats(as_of_date=as_of_date)

    # Combine into stats dict for template
    stats = {
        'revenue_mtd': revenue_stats['mtd'],
        'revenue_ytd': revenue_stats['ytd'],
        'expenses_mtd': expense_stats['mtd'],
        'expenses_ytd': expense_stats['ytd'],
        'receivables_total': receivables_stats['total'],
        'receivables_count': receivables_stats['count'],
        'receivables_overdue': receivables_stats['overdue'],
        'payables_total': payables_stats['total'],
        'payables_count': payables_stats['count'],
        'payables_overdue': payables_stats['overdue']
    }

    # Get top customers and vendors
    top_customers = get_top_customers(limit=5, as_of_date=as_of_date)
    top_vendors = get_top_vendors(limit=5, as_of_date=as_of_date)

    # Get chart data
    revenue_trend = get_monthly_revenue_trend(months=6, as_of_date=as_of_date)
    expense_breakdown = get_expense_breakdown(as_of_date=as_of_date)

    # Action items placeholder (can be enhanced later)
    action_items = []

    return render_template('dashboard/index.html',
                         stats=stats,
                         action_items=action_items,
                         top_customers=top_customers,
                         top_vendors=top_vendors,
                         revenue_trend=revenue_trend,
                         expense_breakdown=expense_breakdown,
                         current_month=as_of_date.strftime('%B %Y'),
                         as_of_date=as_of_date.strftime('%Y-%m-%d'),
                         today=today.strftime('%Y-%m-%d'))

@dashboard_bp.route('/action-items')
@login_required
def action_items():
    """Action Items page - shows all items needing user's action"""
    import json
    items = []

    # Only accountants and admins see pending change requests
    if current_user.role in ['accountant', 'admin']:
        # Chart of Accounts change requests
        coa_requests = AccountChangeRequest.query.filter_by(status='pending').all()
        for req in coa_requests:
            items.append({
                'type': 'AccountChange',
                'id': req.account_code,
                'desc': f'{req.account_name} — {req.action}',
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
                'state': 'Pending',
                'reviewUrl': f'/accounts/review-change-request/{req.id}'
            })

        # VAT Category change requests
        vat_requests = VATCategoryChangeRequest.query.filter_by(status='pending').all()
        for req in vat_requests:
            proposed = json.loads(req.proposed_data) if req.proposed_data else {}
            items.append({
                'type': 'VATChange',
                'id': proposed.get('code', req.id),
                'desc': f"{proposed.get('name', 'VAT Category')} — {req.action}",
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
                'state': 'Pending',
                'reviewUrl': f'/vat-categories/change-requests/{req.id}/review'
            })

        # Withholding Tax change requests
        wt_requests = WithholdingTaxChangeRequest.query.filter_by(status='pending').all()
        for req in wt_requests:
            proposed = json.loads(req.proposed_data) if req.proposed_data else {}
            items.append({
                'type': 'WTChange',
                'id': proposed.get('code', req.id),
                'desc': f"{proposed.get('name', 'Withholding Tax')} — {req.action}",
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
                'state': 'Pending',
                'reviewUrl': f'/withholding-tax/change-requests/{req.id}/review'
            })

    return render_template('dashboard/action_items.html', action_items=items)

@dashboard_bp.route('/api/action-items')
@login_required
def get_action_items():
    """API endpoint to get action items for the current user"""
    items = []

    # Only accountants and admins see pending change requests
    if current_user.role in ['accountant', 'admin']:
        # Chart of Accounts change requests
        coa_requests = AccountChangeRequest.query.filter_by(status='pending').all()
        for req in coa_requests:
            # For create action, just show the name. For update/delete, show "name — action"
            if req.action == 'create':
                desc = req.account_name
            else:
                desc = f'{req.account_name} — {req.action}'
            items.append({
                'type': 'AccountChange',
                'id': req.account_code,
                'desc': desc,
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
                'state': 'Pending',
                'recId': req.id,
                'module': 'accounts',
                'reviewUrl': f'/accounts/review-change-request/{req.id}'
            })

        # VAT Category change requests
        vat_requests = VATCategoryChangeRequest.query.filter_by(status='pending').all()
        for req in vat_requests:
            import json
            proposed = json.loads(req.proposed_data) if req.proposed_data else {}
            # For create action, just show the name. For update/delete, show "name — action"
            if req.action == 'create':
                desc = proposed.get('name', 'VAT Category')
            else:
                desc = f"{proposed.get('name', 'VAT Category')} — {req.action}"
            items.append({
                'type': 'VATChange',
                'id': proposed.get('code', req.id),
                'desc': desc,
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
                'state': 'Pending',
                'recId': req.id,
                'module': 'vat_categories',
                'reviewUrl': f'/vat-categories/change-requests/{req.id}/review'
            })

        # Withholding Tax change requests
        wt_requests = WithholdingTaxChangeRequest.query.filter_by(status='pending').all()
        for req in wt_requests:
            import json
            proposed = json.loads(req.proposed_data) if req.proposed_data else {}
            # For create action, just show the name. For update/delete, show "name — action"
            if req.action == 'create':
                desc = proposed.get('name', 'Withholding Tax')
            else:
                desc = f"{proposed.get('name', 'Withholding Tax')} — {req.action}"
            items.append({
                'type': 'WTChange',
                'id': proposed.get('code', req.id),
                'desc': desc,
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
                'state': 'Pending',
                'recId': req.id,
                'module': 'withholding_tax',
                'reviewUrl': f'/withholding-tax/change-requests/{req.id}/review'
            })

    return jsonify(items)
