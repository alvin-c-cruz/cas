from flask import Blueprint, render_template, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app.accounts.approval_models import AccountChangeRequest
from app.vat_categories.models import VATCategoryChangeRequest
from app.withholding_tax.models import WithholdingTaxChangeRequest

dashboard_bp = Blueprint('dashboard', __name__, template_folder='templates')

@dashboard_bp.route('/')
@login_required
def index():
    """Redirect to dashboard"""
    return redirect(url_for('dashboard.home'))

@dashboard_bp.route('/dashboard')
@login_required
def home():
    """Main dashboard page"""
    # Mock data for dashboard
    stats = {
        'revenue_mtd': 1250000.00,
        'revenue_ytd': 8750000.00,
        'expenses_mtd': 890000.00,
        'expenses_ytd': 6230000.00
    }

    action_items = [
        {'id': 1, 'type': 'JournalEntry', 'description': 'Monthly depreciation entry', 'state': 'Draft', 'user': 'Maria Santos'},
        {'id': 2, 'type': 'Invoice', 'description': 'Invoice #INV-2025-042 awaiting approval', 'state': 'Submitted', 'user': 'Juan dela Cruz'},
        {'id': 3, 'type': 'Bill', 'description': 'Vendor bill from ABC Suppliers', 'state': 'Pending', 'user': 'Maria Santos'},
    ]

    top_customers = [
        {'name': 'ABC Corporation', 'balance': 450000.00, 'invoices': 3},
        {'name': 'XYZ Enterprises', 'balance': 320000.00, 'invoices': 2},
        {'name': 'Global Trading Inc.', 'balance': 280000.00, 'invoices': 4},
        {'name': 'Metro Solutions', 'balance': 175000.00, 'invoices': 1},
        {'name': 'Pacific Holdings', 'balance': 145000.00, 'invoices': 2},
    ]

    top_vendors = [
        {'name': 'Office Depot Philippines', 'balance': 85000.00, 'bills': 2},
        {'name': 'Tech Solutions Inc.', 'balance': 125000.00, 'bills': 1},
        {'name': 'ABC Suppliers', 'balance': 65000.00, 'bills': 3},
    ]

    return render_template('dashboard/index.html',
                         stats=stats,
                         action_items=action_items,
                         top_customers=top_customers,
                         top_vendors=top_vendors)

@dashboard_bp.route('/action-items')
@login_required
def action_items():
    """Action Items page - shows all items needing user's action"""
    return render_template('dashboard/action_items.html')

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
            items.append({
                'type': 'AccountChange',
                'id': req.account_code,
                'desc': f'{req.account_name} — {req.action}',
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
            items.append({
                'type': 'VATChange',
                'id': proposed.get('code', req.id),
                'desc': f"{proposed.get('name', 'VAT Category')} — {req.action}",
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
                'state': 'Pending',
                'recId': req.id,
                'module': 'vat_categories',
                'reviewUrl': f'/vat-categories/review-change-request/{req.id}'
            })

        # Withholding Tax change requests
        wt_requests = WithholdingTaxChangeRequest.query.filter_by(status='pending').all()
        for req in wt_requests:
            import json
            proposed = json.loads(req.proposed_data) if req.proposed_data else {}
            items.append({
                'type': 'WTChange',
                'id': proposed.get('code', req.id),
                'desc': f"{proposed.get('name', 'Withholding Tax')} — {req.action}",
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
                'state': 'Pending',
                'recId': req.id,
                'module': 'withholding_tax',
                'reviewUrl': f'/withholding-tax/review-change-request/{req.id}'
            })

    return jsonify(items)
