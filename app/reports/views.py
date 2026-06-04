"""
Reports views for financial reporting.
Includes AR Aging, AP Aging, and other financial reports.
"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from app import db
from app.sales_invoices.models import SalesInvoice
from app.purchase_bills.models import PurchaseBill
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import func

reports_bp = Blueprint('reports', __name__, template_folder='templates')


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
    """
    Accounts Receivable Aging Report.
    Shows outstanding customer invoices grouped by age.
    """
    # Get as-of date from query params or use today
    as_of_str = request.args.get('as_of', date.today().isoformat())
    as_of_date = date.fromisoformat(as_of_str)

    # Get all posted invoices that are not fully paid
    invoices = SalesInvoice.query.filter(
        SalesInvoice.status == 'posted',
        SalesInvoice.balance_due > 0
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
            'balance_due': invoice.balance_due,
            'bucket': bucket,
            'days_overdue': (as_of_date - invoice.due_date).days if invoice.due_date else 0
        })

        customers[customer_name][bucket] += invoice.balance_due
        customers[customer_name]['total'] += invoice.balance_due

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
    """
    Accounts Payable Aging Report.
    Shows outstanding vendor bills grouped by age.
    """
    # Get as-of date from query params or use today
    as_of_str = request.args.get('as_of', date.today().isoformat())
    as_of_date = date.fromisoformat(as_of_str)

    # Get all posted bills that are not fully paid
    bills = PurchaseBill.query.filter(
        PurchaseBill.status == 'posted',
        PurchaseBill.balance_due > 0
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
            'balance_due': bill.balance_due,
            'bucket': bucket,
            'days_overdue': (as_of_date - bill.due_date).days if bill.due_date else 0
        })

        vendors[vendor_name][bucket] += bill.balance_due
        vendors[vendor_name]['total'] += bill.balance_due

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
