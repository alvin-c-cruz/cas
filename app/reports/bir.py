"""
BIR (Bureau of Internal Revenue) Compliance Reports for Philippine SMEs.

Provides reports required for Philippine tax compliance:
1. Summary List of Sales (Annex A - Monthly VAT Sales)
2. Summary List of Purchases (Annex B - Monthly VAT Purchases)
3. Alphalist of Payees (Quarterly Withholding Tax)

These reports follow BIR format requirements for Philippine businesses.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal
from sqlalchemy import extract
from sqlalchemy.orm import selectinload
from app.accounts_payable.models import AccountsPayable
from app.reports.vat_lines import (
    vat_lines, SALES_BUCKET_BY_NATURE, PURCHASE_BUCKET_BY_NATURE, UNCLASSIFIED,
)

_SALES_KEYS = {
    'vatable': 'vatable_sales',
    'zero_rated': 'zero_rated_sales',
    'exempt': 'vat_exempt_sales',
    'government': 'government_sales',
    UNCLASSIFIED: 'unclassified_sales',
}

# One output key per real purchase nature (identity), plus a renamed
# unclassified key matching the sales-side 'unclassified_sales' convention.
_PURCHASE_KEYS = {b: b for b in PURCHASE_BUCKET_BY_NATURE.values() if b != UNCLASSIFIED}
_PURCHASE_KEYS[UNCLASSIFIED] = 'unclassified_purchases'


def _month_bounds(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def get_summary_list_of_sales(year, month, branch_id=None):
    """Summary List of Sales (BIR Annex A), bucketed by real VAT nature.

    Reads sales_invoice_items AND crv_revenue_lines via vat_lines(); a cash sale
    booked through a CRV used to be invisible here. Lines whose nature is unknown
    land in 'unclassified_sales' -- never silently folded into vatable.
    """
    date_from, date_to = _month_bounds(year, month)
    rows = {}
    for line in vat_lines(date_from, date_to, 'sales', branch_id=branch_id):
        r = rows.setdefault(line.partner_id, {
            'customer_name': line.partner_name,
            'customer_tin': line.partner_tin,
            'customer_address': line.partner_address,
            'total_sales': Decimal('0.00'),
            'vat_amount': Decimal('0.00'),
            'gross_sales': Decimal('0.00'),
            **{k: Decimal('0.00') for k in _SALES_KEYS.values()},
        })
        bucket = SALES_BUCKET_BY_NATURE.get(line.nature, UNCLASSIFIED)
        r[_SALES_KEYS[bucket]] += line.base
        r['total_sales'] += line.base
        r['vat_amount'] += line.vat_amount
        r['gross_sales'] += line.base + line.vat_amount

    summary = sorted(rows.values(), key=lambda x: x['customer_name'])
    if summary:
        numeric = [k for k in summary[0] if isinstance(summary[0][k], Decimal)]
        totals = {'customer_name': 'TOTAL', 'customer_tin': '', 'customer_address': ''}
        totals.update({k: sum(s[k] for s in summary) for k in numeric})
        summary.append(totals)
    return summary


def get_summary_list_of_purchases(year, month, branch_id=None):
    """Summary List of Purchases (BIR Annex B), bucketed by real VAT nature.

    Reads accounts_payable_items AND cdv_expense_lines via vat_lines(); a cash
    purchase booked through a CDV used to be invisible here. Lines whose nature
    is unknown land in 'unclassified_purchases' -- never silently folded into
    a generic vatable bucket.

    Deliberately drops the legacy crude buckets vatable_purchases /
    vat_exempt_purchases / zero_rated_purchases: PURCHASE_BUCKET_BY_NATURE is
    an identity map over the eight real BIR purchase natures, so those three
    keys would always be zero, and no consumer in app/ reads them.
    """
    date_from, date_to = _month_bounds(year, month)
    rows = {}
    doc_nos = {}
    for line in vat_lines(date_from, date_to, 'purchases', branch_id=branch_id):
        r = rows.setdefault(line.partner_id, {
            'vendor_name': line.partner_name,
            'vendor_tin': line.partner_tin,
            'vendor_address': line.partner_address,
            'vendor_invoice_number': '',
            'total_purchases': Decimal('0.00'),
            'input_vat': Decimal('0.00'),
            'gross_purchases': Decimal('0.00'),
            **{k: Decimal('0.00') for k in _PURCHASE_KEYS.values()},
        })
        bucket = PURCHASE_BUCKET_BY_NATURE.get(line.nature, UNCLASSIFIED)
        r[_PURCHASE_KEYS[bucket]] += line.base
        r['total_purchases'] += line.base
        r['input_vat'] += line.vat_amount
        r['gross_purchases'] += line.base + line.vat_amount
        doc_nos.setdefault(line.partner_id, set()).add(line.doc_no)

    for partner_id, r in rows.items():
        distinct = doc_nos[partner_id]
        # Coalesce None -> '' so a bill with no invoice number on file (a real,
        # unremarkable case -- the column is nullable and Optional() at the
        # form layer) never prints the literal string "None" on a filing
        # document. A vendor with one bill carrying None and another carrying
        # a real number is deliberately 'Various' too: None and the real value
        # are two distinct doc_no's, so there is no single number to print.
        r['vendor_invoice_number'] = ('Various' if len(distinct) > 1
                                      else next(iter(distinct)) or '')

    summary = sorted(rows.values(), key=lambda x: x['vendor_name'])
    if summary:
        numeric = [k for k in summary[0] if isinstance(summary[0][k], Decimal)]
        totals = {'vendor_name': 'TOTAL', 'vendor_tin': '', 'vendor_address': '',
                  'vendor_invoice_number': ''}
        totals.update({k: sum(s[k] for s in summary) for k in numeric})
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
    """Quarterly BIR 2550Q data. Company-wide.

    Totals come from the settlement engine (or its immutable snapshot once filed);
    the Part I/II schedules are computed live from posted document lines; and a
    doc-vs-GL reconciliation ties the two sides. The three schedule keys are
    additive -- existing callers keep working on the totals they already read.
    """
    from app.vat_settlement import service
    from app.vat_settlement.models import VatSettlement
    from app.reports.vat_return import build_vat_return_schedules, reconcile_vat_return
    base = {'year': year, 'quarter': quarter, 'quarter_name': get_quarter_name(quarter)}
    settled = VatSettlement.query.filter_by(fiscal_year=year, quarter=quarter,
                                            status='settled').first()
    if settled is not None:
        # Filed quarter: show the immutable snapshot. Re-deriving would trip the tie-out,
        # since the quarter-end settlement JE zeroes the balance side but not the movement side.
        creditable = settled.input_vat + settled.prior_carryover
        result = {**base, 'output_vat': settled.output_vat, 'input_vat': settled.input_vat,
                  'prior_carryover': settled.prior_carryover, 'creditable': creditable,
                  'net_payable': settled.net_payable, 'new_carryover': settled.new_carryover,
                  'settled': True}
        output_gl, input_gl = settled.output_vat, settled.input_vat
    else:
        try:
            pos = service.compute_vat_position(year, quarter)
        except ValueError as e:
            z = Decimal('0.00')
            result = {**base, 'output_vat': z, 'input_vat': z, 'prior_carryover': z,
                      'creditable': z, 'net_payable': z, 'new_carryover': z,
                      'settled': False, 'error': str(e)}
            output_gl = input_gl = None            # GL side unavailable, not zero
        else:
            result = {**base,
                      'output_vat': pos['output_vat'], 'input_vat': pos['input_vat'],
                      'prior_carryover': pos['prior_carryover'], 'creditable': pos['creditable'],
                      'net_payable': pos['net_payable'], 'new_carryover': pos['new_carryover'],
                      'settled': False}
            output_gl, input_gl = pos['output_vat'], pos['input_vat']

    schedules = build_vat_return_schedules(year, quarter)
    result['sales_schedule'] = schedules['sales_schedule']
    result['input_schedule'] = schedules['input_schedule']
    result['reconciliation'] = reconcile_vat_return(output_gl, input_gl, schedules)
    return result
