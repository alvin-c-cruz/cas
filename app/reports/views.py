"""
Reports views for financial reporting.
Includes AR Aging, AP Aging, BIR compliance reports, and financial statements.
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.sales_invoices.models import SalesInvoice
from app.purchase_bills.models import PurchaseBill
from app.reports.bir import (
    get_summary_list_of_sales,
    get_summary_list_of_purchases,
    get_alphalist_of_payees,
    get_month_name,
    get_quarter_name,
    get_quarter_months
)
from app.reports.financial import (
    generate_trial_balance,
    generate_income_statement,
    generate_balance_sheet
)
from app.utils.export import export_to_excel, export_to_csv
from datetime import date, timedelta, datetime
from decimal import Decimal
from sqlalchemy import func

reports_bp = Blueprint('reports', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can access reports.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def calculate_age_bucket(due_date, as_of_date):
    """
    Calculate which age bucket a date falls into.
    Returns: 'current', '1-30', '31-60', '61-90', '90+'
    """
    if not due_date:
        return 'current'

    days_overdue = (as_of_date - due_date).days

    if days_overdue <= 0:
        return 'current'
    elif days_overdue <= 30:
        return '1-30'
    elif days_overdue <= 60:
        return '31-60'
    elif days_overdue <= 90:
        return '61-90'
    else:
        return '90+'


@reports_bp.route('/reports')
@login_required
def index():
    """Reports dashboard."""
    return render_template('reports/index.html')


@reports_bp.route('/reports/ar-aging')
@login_required
def ar_aging():
    return redirect(url_for('dashboard.under_development', feature='AR Aging'))
    as_of_str = request.args.get('as_of', date.today().isoformat())
    as_of_date = date.fromisoformat(as_of_str)

    # Get all posted invoices that are not fully paid — scoped to current branch
    current_branch_id = session.get('selected_branch_id')
    invoices = SalesInvoice.query.filter(
        SalesInvoice.status == 'posted',
        SalesInvoice.balance > 0,
        SalesInvoice.branch_id == current_branch_id
    ).order_by(SalesInvoice.customer_name, SalesInvoice.due_date).all()

    # Group by customer
    customers = {}

    for invoice in invoices:
        customer_name = invoice.customer_name
        if customer_name not in customers:
            customers[customer_name] = {
                'name': customer_name,
                'invoices': [],
                'current': Decimal('0.00'),
                '1-30': Decimal('0.00'),
                '31-60': Decimal('0.00'),
                '61-90': Decimal('0.00'),
                '90+': Decimal('0.00'),
                'total': Decimal('0.00')
            }

        # Calculate age bucket
        bucket = calculate_age_bucket(invoice.due_date, as_of_date)

        # Add to customer totals
        customers[customer_name]['invoices'].append({
            'invoice_number': invoice.invoice_number,
            'invoice_date': invoice.invoice_date,
            'due_date': invoice.due_date,
            'balance_due': invoice.balance,
            'bucket': bucket,
            'days_overdue': (as_of_date - invoice.due_date).days if invoice.due_date else 0
        })

        customers[customer_name][bucket] += invoice.balance
        customers[customer_name]['total'] += invoice.balance

    # Calculate grand totals
    grand_totals = {
        'current': Decimal('0.00'),
        '1-30': Decimal('0.00'),
        '31-60': Decimal('0.00'),
        '61-90': Decimal('0.00'),
        '90+': Decimal('0.00'),
        'total': Decimal('0.00')
    }

    for customer_data in customers.values():
        grand_totals['current'] += customer_data['current']
        grand_totals['1-30'] += customer_data['1-30']
        grand_totals['31-60'] += customer_data['31-60']
        grand_totals['61-90'] += customer_data['61-90']
        grand_totals['90+'] += customer_data['90+']
        grand_totals['total'] += customer_data['total']

    # Sort customers by total balance (descending)
    customers_list = sorted(customers.values(), key=lambda x: x['total'], reverse=True)

    return render_template('reports/ar_aging.html',
                         customers=customers_list,
                         grand_totals=grand_totals,
                         as_of_date=as_of_date)


@reports_bp.route('/reports/ap-aging')
@login_required
def ap_aging():
    return redirect(url_for('dashboard.under_development', feature='AP Aging'))
    as_of_str = request.args.get('as_of', date.today().isoformat())
    as_of_date = date.fromisoformat(as_of_str)

    # Get all posted bills that are not fully paid — scoped to current branch
    current_branch_id = session.get('selected_branch_id')
    bills = PurchaseBill.query.filter(
        PurchaseBill.status == 'posted',
        PurchaseBill.balance > 0,
        PurchaseBill.branch_id == current_branch_id
    ).order_by(PurchaseBill.vendor_name, PurchaseBill.due_date).all()

    # Group by vendor
    vendors = {}

    for bill in bills:
        vendor_name = bill.vendor_name
        if vendor_name not in vendors:
            vendors[vendor_name] = {
                'name': vendor_name,
                'bills': [],
                'current': Decimal('0.00'),
                '1-30': Decimal('0.00'),
                '31-60': Decimal('0.00'),
                '61-90': Decimal('0.00'),
                '90+': Decimal('0.00'),
                'total': Decimal('0.00')
            }

        # Calculate age bucket
        bucket = calculate_age_bucket(bill.due_date, as_of_date)

        # Add to vendor totals
        vendors[vendor_name]['bills'].append({
            'bill_number': bill.bill_number,
            'bill_date': bill.bill_date,
            'due_date': bill.due_date,
            'balance_due': bill.balance,
            'bucket': bucket,
            'days_overdue': (as_of_date - bill.due_date).days if bill.due_date else 0
        })

        vendors[vendor_name][bucket] += bill.balance
        vendors[vendor_name]['total'] += bill.balance

    # Calculate grand totals
    grand_totals = {
        'current': Decimal('0.00'),
        '1-30': Decimal('0.00'),
        '31-60': Decimal('0.00'),
        '61-90': Decimal('0.00'),
        '90+': Decimal('0.00'),
        'total': Decimal('0.00')
    }

    for vendor_data in vendors.values():
        grand_totals['current'] += vendor_data['current']
        grand_totals['1-30'] += vendor_data['1-30']
        grand_totals['31-60'] += vendor_data['31-60']
        grand_totals['61-90'] += vendor_data['61-90']
        grand_totals['90+'] += vendor_data['90+']
        grand_totals['total'] += vendor_data['total']

    # Sort vendors by total balance (descending)
    vendors_list = sorted(vendors.values(), key=lambda x: x['total'], reverse=True)

    return render_template('reports/ap_aging.html',
                         vendors=vendors_list,
                         grand_totals=grand_totals,
                         as_of_date=as_of_date)


# BIR Compliance Reports

@reports_bp.route('/reports/bir')
@login_required
@accountant_or_admin_required
def bir_index():
    return redirect(url_for('dashboard.under_development', feature='BIR Reports'))
    current_year = datetime.now().year
    current_month = datetime.now().month
    current_quarter = ((current_month - 1) // 3) + 1

    return render_template('reports/bir_index.html',
                         current_year=current_year,
                         current_month=current_month,
                         current_quarter=current_quarter)


@reports_bp.route('/reports/bir/sales')
@login_required
@accountant_or_admin_required
def bir_sales():
    """Summary List of Sales (Annex A) - Monthly VAT Sales"""
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    current_branch_id = session.get('selected_branch_id')
    sales_data = get_summary_list_of_sales(year, month, branch_id=current_branch_id)

    return render_template('reports/bir_sales.html',
                         sales_data=sales_data,
                         year=year,
                         month=month,
                         month_name=get_month_name(month))


@reports_bp.route('/reports/bir/sales/export/excel')
@login_required
@accountant_or_admin_required
def bir_sales_export_excel():
    """Export Summary List of Sales to Excel"""
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    current_branch_id = session.get('selected_branch_id')
    sales_data = get_summary_list_of_sales(year, month, branch_id=current_branch_id)

    columns = ['customer_tin', 'customer_name', 'customer_address', 'vatable_sales',
               'vat_exempt_sales', 'zero_rated_sales', 'vat_amount', 'gross_sales']
    headers = ['TIN', 'Customer Name', 'Address', 'Vatable Sales',
               'VAT-Exempt Sales', 'Zero-Rated Sales', 'Output VAT', 'Gross Sales']

    filename = f'BIR_Summary_Sales_{year}_{month:02d}.xlsx'
    title = f'Summary List of Sales - {get_month_name(month)} {year}'

    return export_to_excel(sales_data, columns, headers, filename, title)


@reports_bp.route('/reports/bir/purchases')
@login_required
@accountant_or_admin_required
def bir_purchases():
    """Summary List of Purchases (Annex B) - Monthly VAT Purchases"""
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    current_branch_id = session.get('selected_branch_id')
    purchases_data = get_summary_list_of_purchases(year, month, branch_id=current_branch_id)

    return render_template('reports/bir_purchases.html',
                         purchases_data=purchases_data,
                         year=year,
                         month=month,
                         month_name=get_month_name(month))


@reports_bp.route('/reports/bir/purchases/export/excel')
@login_required
@accountant_or_admin_required
def bir_purchases_export_excel():
    """Export Summary List of Purchases to Excel"""
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    current_branch_id = session.get('selected_branch_id')
    purchases_data = get_summary_list_of_purchases(year, month, branch_id=current_branch_id)

    columns = ['vendor_tin', 'vendor_name', 'vendor_address', 'vendor_invoice_number',
               'vatable_purchases', 'vat_exempt_purchases', 'zero_rated_purchases',
               'input_vat', 'gross_purchases']
    headers = ['TIN', 'Vendor Name', 'Address', 'Invoice #', 'Vatable Purchases',
               'VAT-Exempt Purchases', 'Zero-Rated Purchases', 'Input VAT', 'Gross Purchases']

    filename = f'BIR_Summary_Purchases_{year}_{month:02d}.xlsx'
    title = f'Summary List of Purchases - {get_month_name(month)} {year}'

    return export_to_excel(purchases_data, columns, headers, filename, title)


@reports_bp.route('/reports/bir/alphalist')
@login_required
@accountant_or_admin_required
def bir_alphalist():
    return redirect(url_for('dashboard.under_development', feature='BIR Alphalist'))
    year = request.args.get('year', datetime.now().year, type=int)
    quarter = request.args.get('quarter', ((datetime.now().month - 1) // 3) + 1, type=int)
    current_branch_id = session.get('selected_branch_id')
    payees_data = get_alphalist_of_payees(year, quarter, branch_id=current_branch_id)

    return render_template('reports/bir_alphalist.html',
                         payees_data=payees_data,
                         year=year,
                         quarter=quarter,
                         quarter_name=get_quarter_name(quarter),
                         quarter_months=get_quarter_months(quarter))


@reports_bp.route('/reports/bir/alphalist/export/excel')
@login_required
@accountant_or_admin_required
def bir_alphalist_export_excel():
    """Export Alphalist of Payees to Excel"""
    year = request.args.get('year', datetime.now().year, type=int)
    quarter = request.args.get('quarter', ((datetime.now().month - 1) // 3) + 1, type=int)
    current_branch_id = session.get('selected_branch_id')
    payees_data = get_alphalist_of_payees(year, quarter, branch_id=current_branch_id)

    columns = ['payee_tin', 'payee_name', 'payee_address', 'atc_code',
               'tax_rate', 'gross_income', 'tax_withheld', 'month_paid']
    headers = ['TIN', 'Payee Name', 'Address', 'ATC Code',
               'Tax Rate (%)', 'Gross Income', 'Tax Withheld', 'Month/s Paid']

    filename = f'BIR_Alphalist_Payees_{year}_Q{quarter}.xlsx'
    title = f'Alphalist of Payees - {get_quarter_name(quarter)} {year}'

    return export_to_excel(payees_data, columns, headers, filename, title)


# ============================================================================
# FINANCIAL STATEMENTS
# ============================================================================

@reports_bp.route('/reports/trial-balance')
@login_required
@accountant_or_admin_required
def trial_balance():
    return redirect(url_for('dashboard.under_development', feature='Trial Balance'))
    as_of_str = request.args.get('as_of', date.today().isoformat())
    as_of_date = date.fromisoformat(as_of_str)

    # Generate trial balance — scoped to current branch
    current_branch_id = session.get('selected_branch_id')
    trial_balance_data = generate_trial_balance(as_of_date, branch_id=current_branch_id)

    return render_template('reports/trial_balance.html',
                         trial_balance=trial_balance_data,
                         as_of_date=as_of_date)


@reports_bp.route('/reports/trial-balance/export/excel')
@login_required
@accountant_or_admin_required
def trial_balance_export_excel():
    """Export Trial Balance to Excel"""
    as_of_str = request.args.get('as_of', date.today().isoformat())
    as_of_date = date.fromisoformat(as_of_str)

    current_branch_id = session.get('selected_branch_id')
    trial_balance_data = generate_trial_balance(as_of_date, branch_id=current_branch_id)

    columns = ['code', 'name', 'debit_balance', 'credit_balance']
    headers = ['Account Code', 'Account Name', 'Debit', 'Credit']

    filename = f'Trial_Balance_{as_of_date.isoformat()}.xlsx'
    title = f'Trial Balance - As of {as_of_date.strftime("%B %d, %Y")}'

    return export_to_excel(trial_balance_data['accounts'], columns, headers, filename, title)


@reports_bp.route('/reports/income-statement')
@login_required
@accountant_or_admin_required
def income_statement():
    return redirect(url_for('dashboard.under_development', feature='Income Statement'))
    today = date.today()
    start_str = request.args.get('start_date', date(today.year, today.month, 1).isoformat())
    end_str = request.args.get('end_date', today.isoformat())

    start_date = date.fromisoformat(start_str)
    end_date = date.fromisoformat(end_str)

    # Generate income statement — scoped to current branch
    current_branch_id = session.get('selected_branch_id')
    income_stmt_data = generate_income_statement(start_date, end_date, branch_id=current_branch_id)

    return render_template('reports/income_statement.html',
                         income_statement=income_stmt_data,
                         start_date=start_date,
                         end_date=end_date)


@reports_bp.route('/reports/income-statement/export/excel')
@login_required
@accountant_or_admin_required
def income_statement_export_excel():
    """Export Income Statement to Excel"""
    today = date.today()
    start_str = request.args.get('start_date', date(today.year, today.month, 1).isoformat())
    end_str = request.args.get('end_date', today.isoformat())

    start_date = date.fromisoformat(start_str)
    end_date = date.fromisoformat(end_str)

    current_branch_id = session.get('selected_branch_id')
    income_stmt_data = generate_income_statement(start_date, end_date, branch_id=current_branch_id)

    # Combine revenue and expenses for export
    data = []

    # Add revenue section
    for item in income_stmt_data['revenue']:
        data.append({
            'code': item['code'],
            'name': item['name'],
            'amount': item['amount'],
            'section': 'Revenue'
        })

    # Add expenses section
    for item in income_stmt_data['expenses']:
        data.append({
            'code': item['code'],
            'name': item['name'],
            'amount': item['amount'],
            'section': 'Expenses'
        })

    columns = ['section', 'code', 'name', 'amount']
    headers = ['Section', 'Code', 'Account Name', 'Amount']

    filename = f'Income_Statement_{start_date.isoformat()}_to_{end_date.isoformat()}.xlsx'
    title = f'Income Statement - {start_date.strftime("%b %d, %Y")} to {end_date.strftime("%b %d, %Y")}'

    return export_to_excel(data, columns, headers, filename, title)


@reports_bp.route('/reports/balance-sheet')
@login_required
@accountant_or_admin_required
def balance_sheet():
    return redirect(url_for('dashboard.under_development', feature='Balance Sheet'))
    as_of_str = request.args.get('as_of', date.today().isoformat())
    as_of_date = date.fromisoformat(as_of_str)

    # Generate balance sheet — scoped to current branch
    current_branch_id = session.get('selected_branch_id')
    balance_sheet_data = generate_balance_sheet(as_of_date, branch_id=current_branch_id)

    return render_template('reports/balance_sheet.html',
                         balance_sheet=balance_sheet_data,
                         as_of_date=as_of_date)


@reports_bp.route('/reports/balance-sheet/export/excel')
@login_required
@accountant_or_admin_required
def balance_sheet_export_excel():
    """Export Balance Sheet to Excel"""
    as_of_str = request.args.get('as_of', date.today().isoformat())
    as_of_date = date.fromisoformat(as_of_str)

    current_branch_id = session.get('selected_branch_id')
    balance_sheet_data = generate_balance_sheet(as_of_date, branch_id=current_branch_id)

    # Combine assets, liabilities, and equity for export
    data = []

    # Add assets
    for item in balance_sheet_data['assets']:
        data.append({
            'code': item['code'],
            'name': item['name'],
            'amount': item['amount'],
            'section': 'Assets'
        })

    # Add liabilities
    for item in balance_sheet_data['liabilities']:
        data.append({
            'code': item['code'],
            'name': item['name'],
            'amount': item['amount'],
            'section': 'Liabilities'
        })

    # Add equity
    for item in balance_sheet_data['equity']:
        data.append({
            'code': item['code'],
            'name': item['name'],
            'amount': item['amount'],
            'section': 'Equity'
        })

    columns = ['section', 'code', 'name', 'amount']
    headers = ['Section', 'Code', 'Account Name', 'Amount']

    filename = f'Balance_Sheet_{as_of_date.isoformat()}.xlsx'
    title = f'Balance Sheet - As of {as_of_date.strftime("%B %d, %Y")}'

    return export_to_excel(data, columns, headers, filename, title)
