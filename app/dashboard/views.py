from flask import Blueprint, render_template, redirect, url_for

dashboard_bp = Blueprint('dashboard', __name__, template_folder='templates')

@dashboard_bp.route('/')
def index():
    """Redirect to dashboard"""
    return redirect(url_for('dashboard.home'))

@dashboard_bp.route('/dashboard')
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
