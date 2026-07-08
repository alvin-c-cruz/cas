"""
BIR (Bureau of Internal Revenue) Compliance Reports for Philippine SMEs.

Provides reports required for Philippine tax compliance:
1. Summary List of Sales (Annex A - Monthly VAT Sales)
2. Summary List of Purchases (Annex B - Monthly VAT Purchases)
3. Alphalist of Payees (Quarterly Withholding Tax)

These reports follow BIR format requirements for Philippine businesses.
"""
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import func, extract
from sqlalchemy.orm import selectinload
from app import db
from app.sales_invoices.models import SalesInvoice
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.customers.models import Customer
from app.vendors.models import Vendor


def get_summary_list_of_sales(year, month, branch_id=None):
    """
    Generate Summary List of Sales (Annex A) - VAT Sales Report

    BIR requirement: Monthly summary of sales with VAT breakdown

    Args:
        year: Year (e.g., 2026)
        month: Month (1-12)
        branch_id: Branch to filter by (None = all branches)

    Returns:
        List of dicts with sales summary by customer
    """
    # Query posted sales invoices for the specified month
    query = SalesInvoice.query.filter(
        extract('year', SalesInvoice.invoice_date) == year,
        extract('month', SalesInvoice.invoice_date) == month,
        SalesInvoice.status.in_(['posted', 'paid', 'partially_paid'])
    )
    if branch_id:
        query = query.filter(SalesInvoice.branch_id == branch_id)
    invoices = query.all()

    # Group by customer and calculate totals
    customer_totals = {}

    for invoice in invoices:
        customer_key = invoice.customer_id

        if customer_key not in customer_totals:
            customer_totals[customer_key] = {
                'customer_name': invoice.customer_name,
                'customer_tin': invoice.customer_tin or '',
                'customer_address': invoice.customer_address or '',
                'total_sales': Decimal('0.00'),
                'vatable_sales': Decimal('0.00'),
                'vat_exempt_sales': Decimal('0.00'),
                'zero_rated_sales': Decimal('0.00'),
                'vat_amount': Decimal('0.00'),
                'gross_sales': Decimal('0.00')
            }

        # Add to totals
        customer_totals[customer_key]['total_sales'] += invoice.subtotal
        customer_totals[customer_key]['vat_amount'] += invoice.vat_amount
        customer_totals[customer_key]['gross_sales'] += invoice.total_amount

        # For now, treat all sales as vatable (can be enhanced later)
        customer_totals[customer_key]['vatable_sales'] += invoice.subtotal

    # Convert to list and sort by customer name
    summary = list(customer_totals.values())
    summary.sort(key=lambda x: x['customer_name'])

    # Add totals row
    if summary:
        totals = {
            'customer_name': 'TOTAL',
            'customer_tin': '',
            'customer_address': '',
            'total_sales': sum(s['total_sales'] for s in summary),
            'vatable_sales': sum(s['vatable_sales'] for s in summary),
            'vat_exempt_sales': sum(s['vat_exempt_sales'] for s in summary),
            'zero_rated_sales': sum(s['zero_rated_sales'] for s in summary),
            'vat_amount': sum(s['vat_amount'] for s in summary),
            'gross_sales': sum(s['gross_sales'] for s in summary)
        }
        summary.append(totals)

    return summary


def get_summary_list_of_purchases(year, month, branch_id=None):
    """
    Generate Summary List of Purchases (Annex B) - VAT Purchases Report

    BIR requirement: Monthly summary of purchases with input VAT

    Args:
        year: Year (e.g., 2026)
        month: Month (1-12)
        branch_id: Branch to filter by (None = all branches)

    Returns:
        List of dicts with purchases summary by vendor
    """
    # Query posted purchase bills for the specified month
    query = AccountsPayable.query.filter(
        extract('year', AccountsPayable.ap_date) == year,
        extract('month', AccountsPayable.ap_date) == month,
        AccountsPayable.status.in_(['posted', 'paid', 'partially_paid'])
    )
    if branch_id:
        query = query.filter(AccountsPayable.branch_id == branch_id)
    bills = query.all()

    # Group by vendor and calculate totals
    vendor_totals = {}

    for bill in bills:
        vendor_key = bill.vendor_id

        if vendor_key not in vendor_totals:
            vendor_totals[vendor_key] = {
                'vendor_name': bill.vendor_name,
                'vendor_tin': bill.vendor_tin or '',
                'vendor_address': bill.vendor_address or '',
                'vendor_invoice_number': '',  # Multiple invoices, will show "Various"
                'total_purchases': Decimal('0.00'),
                'vatable_purchases': Decimal('0.00'),
                'vat_exempt_purchases': Decimal('0.00'),
                'zero_rated_purchases': Decimal('0.00'),
                'input_vat': Decimal('0.00'),
                'gross_purchases': Decimal('0.00')
            }

        # Add to totals
        vendor_totals[vendor_key]['total_purchases'] += bill.subtotal
        vendor_totals[vendor_key]['input_vat'] += bill.vat_amount
        vendor_totals[vendor_key]['gross_purchases'] += bill.total_before_wt

        # For now, treat all purchases as vatable (can be enhanced later)
        vendor_totals[vendor_key]['vatable_purchases'] += bill.subtotal

    # Mark vendors with multiple invoices
    for vendor_key, totals in vendor_totals.items():
        invoice_count = len([b for b in bills if b.vendor_id == vendor_key])
        if invoice_count > 1:
            totals['vendor_invoice_number'] = 'Various'
        else:
            bill = next(b for b in bills if b.vendor_id == vendor_key)
            totals['vendor_invoice_number'] = bill.vendor_invoice_number or ''

    # Convert to list and sort by vendor name
    summary = list(vendor_totals.values())
    summary.sort(key=lambda x: x['vendor_name'])

    # Add totals row
    if summary:
        totals = {
            'vendor_name': 'TOTAL',
            'vendor_tin': '',
            'vendor_address': '',
            'vendor_invoice_number': '',
            'total_purchases': sum(s['total_purchases'] for s in summary),
            'vatable_purchases': sum(s['vatable_purchases'] for s in summary),
            'vat_exempt_purchases': sum(s['vat_exempt_purchases'] for s in summary),
            'zero_rated_purchases': sum(s['zero_rated_purchases'] for s in summary),
            'input_vat': sum(s['input_vat'] for s in summary),
            'gross_purchases': sum(s['gross_purchases'] for s in summary)
        }
        summary.append(totals)

    return summary


def get_alphalist_of_payees(year, quarter, branch_id=None):
    """
    Generate Alphalist of Payees - Quarterly Withholding Tax Report

    BIR requirement: Quarterly report of withholding tax payments

    Args:
        year: Year (e.g., 2026)
        quarter: Quarter (1-4)
        branch_id: Branch to filter by (None = all branches)

    Returns:
        List of dicts with withholding tax summary by payee
    """
    # Calculate month range for quarter
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2

    # Query purchase bills with withholding tax
    query = AccountsPayable.query.filter(
        extract('year', AccountsPayable.ap_date) == year,
        extract('month', AccountsPayable.ap_date) >= start_month,
        extract('month', AccountsPayable.ap_date) <= end_month,
        AccountsPayable.status.in_(['posted', 'paid', 'partially_paid']),
        AccountsPayable.withholding_tax_amount > 0
    )
    if branch_id:
        query = query.filter(AccountsPayable.branch_id == branch_id)
    bills = query.options(selectinload(AccountsPayable.line_items)).all()

    # Group by vendor (payee) and calculate totals
    payee_totals = {}

    from collections import defaultdict

    for bill in bills:
        wt_groups = defaultdict(list)
        for item in bill.line_items:
            if item.wt_id and item.wt_amount and item.wt_amount > 0:
                wt_groups[item.wt_id].append(item)

        for wt_id, items in wt_groups.items():
            wt = items[0].withholding_tax
            row_key = (bill.vendor_id, wt_id)

            if row_key not in payee_totals:
                payee_totals[row_key] = {
                    'payee_name': bill.vendor_name,
                    'payee_tin': bill.vendor_tin or '',
                    'payee_address': bill.vendor_address or '',
                    'atc_code': wt.code if wt else '',
                    'tax_rate': float(wt.rate) if wt else 0.0,
                    'gross_income': Decimal('0.00'),
                    'tax_withheld': Decimal('0.00'),
                    'month_paid': [],
                }

            payee_totals[row_key]['gross_income'] += sum(i.line_total for i in items)
            payee_totals[row_key]['tax_withheld'] += sum(i.wt_amount for i in items)

            month = bill.ap_date.month
            if month not in payee_totals[row_key]['month_paid']:
                payee_totals[row_key]['month_paid'].append(month)

    # Convert month list to string
    for payee_key, totals in payee_totals.items():
        months = sorted(totals['month_paid'])
        month_names = {
            1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
            7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
        }
        totals['month_paid'] = ', '.join([month_names[m] for m in months])

    # Convert to list and sort alphabetically by payee name
    summary = list(payee_totals.values())
    summary.sort(key=lambda x: x['payee_name'])

    # Add totals row
    if summary:
        totals = {
            'payee_name': 'TOTAL',
            'payee_tin': '',
            'payee_address': '',
            'atc_code': '',
            'tax_rate': '',
            'gross_income': sum(s['gross_income'] for s in summary),
            'tax_withheld': sum(s['tax_withheld'] for s in summary),
            'month_paid': ''
        }
        summary.append(totals)

    return summary


def get_month_name(month):
    """Get month name from month number"""
    month_names = {
        1: 'January', 2: 'February', 3: 'March', 4: 'April',
        5: 'May', 6: 'June', 7: 'July', 8: 'August',
        9: 'September', 10: 'October', 11: 'November', 12: 'December'
    }
    return month_names.get(month, '')


def get_quarter_name(quarter):
    """Get quarter name from quarter number"""
    quarter_names = {
        1: '1st Quarter (Jan-Mar)',
        2: '2nd Quarter (Apr-Jun)',
        3: '3rd Quarter (Jul-Sep)',
        4: '4th Quarter (Oct-Dec)'
    }
    return quarter_names.get(quarter, '')


def get_quarter_months(quarter):
    """Get month range for quarter"""
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    return f'{get_month_name(start_month)} - {get_month_name(end_month)}'


def get_vat_return_summary(year, quarter):
    """Quarterly net-VAT worksheet (BIR 2550Q pre-cursor). Company-wide."""
    from app.vat_settlement import service
    from app.vat_settlement.models import VatSettlement
    base = {'year': year, 'quarter': quarter, 'quarter_name': get_quarter_name(quarter)}
    settled = VatSettlement.query.filter_by(fiscal_year=year, quarter=quarter,
                                            status='settled').first()
    if settled is not None:
        # Filed quarter: show the immutable snapshot. Re-deriving would trip the tie-out,
        # since the quarter-end settlement JE zeroes the balance side but not the movement side.
        creditable = settled.input_vat + settled.prior_carryover
        return {**base, 'output_vat': settled.output_vat, 'input_vat': settled.input_vat,
                'prior_carryover': settled.prior_carryover, 'creditable': creditable,
                'net_payable': settled.net_payable, 'new_carryover': settled.new_carryover,
                'settled': True}
    try:
        pos = service.compute_vat_position(year, quarter)
    except ValueError as e:
        z = Decimal('0.00')
        return {**base, 'output_vat': z, 'input_vat': z, 'prior_carryover': z,
                'creditable': z, 'net_payable': z, 'new_carryover': z, 'error': str(e)}
    return {**base,
            'output_vat': pos['output_vat'], 'input_vat': pos['input_vat'],
            'prior_carryover': pos['prior_carryover'], 'creditable': pos['creditable'],
            'net_payable': pos['net_payable'], 'new_carryover': pos['new_carryover'],
            'settled': False}
