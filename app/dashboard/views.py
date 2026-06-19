import json
from flask import Blueprint, render_template, redirect, url_for, jsonify, request, session, flash
from flask_login import login_required, current_user
from app.dashboard.action_items_service import gather_draft_items, gather_approval_items
from datetime import datetime
from app.utils import ph_now
from app.accounts.approval_models import AccountChangeRequest
from app.vat_categories.models import VATCategoryChangeRequest
from app.withholding_tax.models import WithholdingTaxChangeRequest
from app.dashboard.dashboard_data import (
    get_revenue_stats, get_expense_stats,
    get_receivables_stats, get_payables_stats,
    get_top_customers, get_top_vendors,
    get_monthly_revenue_trend, get_expense_breakdown,
    get_active_accounts
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
    # Get "as of" date from query parameter or default to today
    today = ph_now().date()
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

    # Fetch the active Revenue/Expense account lists once and share them across
    # the helpers below, instead of each helper re-querying them (FINDING-002).
    revenue_accounts = get_active_accounts('Revenue')
    expense_accounts = get_active_accounts('Expense')

    # Get real financial statistics (filtered by current branch and as_of_date)
    revenue_stats = get_revenue_stats(current_year, current_month, branch_id=current_branch_id, as_of_date=as_of_date, revenue_accounts=revenue_accounts)
    expense_stats = get_expense_stats(current_year, current_month, branch_id=current_branch_id, as_of_date=as_of_date, expense_accounts=expense_accounts)
    receivables_stats = get_receivables_stats(as_of_date=as_of_date, branch_id=current_branch_id)
    payables_stats = get_payables_stats(as_of_date=as_of_date, branch_id=current_branch_id)

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
    top_customers = get_top_customers(limit=5, as_of_date=as_of_date, branch_id=current_branch_id)
    top_vendors = get_top_vendors(limit=5, as_of_date=as_of_date, branch_id=current_branch_id)

    # Get chart data (reuse the account lists fetched above — FINDING-002)
    revenue_trend = get_monthly_revenue_trend(months=6, as_of_date=as_of_date, branch_id=current_branch_id, revenue_accounts=revenue_accounts)
    expense_breakdown = get_expense_breakdown(as_of_date=as_of_date, branch_id=current_branch_id, expense_accounts=expense_accounts)

    return render_template('dashboard/index.html',
                         stats=stats,
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
    """Action Items page — drafts to finish and change requests to approve."""
    # Viewers have no action items; keep them off the page entirely.
    if current_user.role == 'viewer':
        flash('You do not have access to Action Items.', 'warning')
        return redirect(url_for('dashboard.home'))

    branch_id = session.get('selected_branch_id')
    draft_items = gather_draft_items(current_user, branch_id)
    approval_items = gather_approval_items(current_user)
    return render_template('dashboard/action_items.html',
                           draft_items=draft_items, approval_items=approval_items)

@dashboard_bp.route('/api/action-items')
@login_required
def get_action_items():
    """API endpoint: the current user's drafts + approvals (same rules as the
    Action Items page)."""
    if current_user.role == 'viewer':
        return jsonify([])
    branch_id = session.get('selected_branch_id')
    items = gather_draft_items(current_user, branch_id) + gather_approval_items(current_user)
    return jsonify(items)

@dashboard_bp.route('/under-development')
@login_required
def under_development():
    feature = request.args.get('feature', '')
    return render_template('dashboard/under_development.html', feature=feature)
