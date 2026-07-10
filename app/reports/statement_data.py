# app/reports/statement_data.py
"""Pure builder for the customer Statement of Account (SOA).

Event-sources every AR-moving document by its document date so the running balance
reconstructs any historical period (the live `balance` fields are as-of-now, not
as-of-a-past-date). No Flask/request access here — callers pass ids + a resolved period.
"""
from decimal import Decimal

from app.sales_invoices.models import SalesInvoice
from app.sales_memos.models import SalesMemo
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine

# Same-date ordering: charges before credits; SI, then DN, then CM, then payment.
_KIND_RANK = {'invoice': 0, 'debit_note': 1, 'credit_memo': 2, 'payment': 3}

_ACTIVE_SI = ['posted', 'partially_paid', 'paid']


def _collect_events(customer_id, branch_id):
    """Every AR-moving event for a customer+branch (no date filter), as row dicts."""
    events = []

    for i in SalesInvoice.query.filter(
            SalesInvoice.customer_id == customer_id,
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status.in_(_ACTIVE_SI)).all():
        events.append({'date': i.invoice_date, 'kind': 'invoice', 'doc_type': 'invoice',
                       'doc_id': i.id, 'doc_number': i.invoice_number,
                       'particulars': 'Sales Invoice',
                       'charge': Decimal(str(i.total_amount)), 'credit': Decimal('0.00')})

    for m in SalesMemo.query.filter(
            SalesMemo.customer_id == customer_id, SalesMemo.branch_id == branch_id,
            SalesMemo.memo_type == 'debit', SalesMemo.status == 'posted').all():
        events.append({'date': m.memo_date, 'kind': 'debit_note', 'doc_type': 'debit_note',
                       'doc_id': m.id, 'doc_number': m.memo_number,
                       'particulars': 'Debit Note',
                       'charge': Decimal(str(m.total_amount)), 'credit': Decimal('0.00')})

    for m in SalesMemo.query.filter(
            SalesMemo.customer_id == customer_id, SalesMemo.branch_id == branch_id,
            SalesMemo.memo_type == 'credit', SalesMemo.destination == 'ar',
            SalesMemo.status == 'posted').all():
        events.append({'date': m.memo_date, 'kind': 'credit_memo', 'doc_type': 'credit_memo',
                       'doc_id': m.id, 'doc_number': m.memo_number,
                       'particulars': 'Credit Memo',
                       'charge': Decimal('0.00'), 'credit': Decimal(str(m.total_amount))})

    for line in CRVArLine.query.join(
            CashReceiptVoucher, CRVArLine.crv_id == CashReceiptVoucher.id).filter(
            CashReceiptVoucher.customer_id == customer_id,
            CashReceiptVoucher.branch_id == branch_id,
            CashReceiptVoucher.status == 'posted').all():
        crv = line.crv
        events.append({'date': crv.crv_date, 'kind': 'payment', 'doc_type': 'crv',
                       'doc_id': crv.id, 'doc_number': crv.crv_number,
                       'particulars': f'Collection ({line.invoice_number})',
                       'charge': Decimal('0.00'), 'credit': Decimal(str(line.amount_applied))})

    return events


_BUCKETS = ['current', '1-30', '31-60', '61-90', '90+']


def _age_bucket(bucket_date, as_of):
    """Mirror of app/reports/views.py::calculate_age_bucket (kept local so the pure
    builder does not import the Flask views module)."""
    if not bucket_date:
        return 'current'
    days_overdue = (as_of - bucket_date).days
    if days_overdue <= 0:
        return 'current'
    if days_overdue <= 30:
        return '1-30'
    if days_overdue <= 60:
        return '31-60'
    if days_overdue <= 90:
        return '61-90'
    return '90+'


def _crv_applied_to(as_of, invoice_id=None, sales_memo_id=None):
    """Sum of posted-CRV amounts applied to one document on or before `as_of`."""
    q = CRVArLine.query.join(
        CashReceiptVoucher, CRVArLine.crv_id == CashReceiptVoucher.id).filter(
        CashReceiptVoucher.status == 'posted',
        CashReceiptVoucher.crv_date <= as_of)
    if invoice_id is not None:
        q = q.filter(CRVArLine.invoice_id == invoice_id)
    else:
        q = q.filter(CRVArLine.sales_memo_id == sales_memo_id)
    return sum((Decimal(str(l.amount_applied)) for l in q.all()), Decimal('0.00'))


def _cm_applied_to_si(si_id, as_of):
    """Sum of ar-dest credit memos against one SI on or before `as_of`."""
    q = SalesMemo.query.filter(
        SalesMemo.memo_type == 'credit', SalesMemo.destination == 'ar',
        SalesMemo.status == 'posted', SalesMemo.sales_invoice_id == si_id,
        SalesMemo.memo_date <= as_of)
    return sum((Decimal(str(m.total_amount)) for m in q.all()), Decimal('0.00'))


def _age_open_items(customer_id, branch_id, as_of):
    buckets = {b: Decimal('0.00') for b in _BUCKETS}

    for i in SalesInvoice.query.filter(
            SalesInvoice.customer_id == customer_id, SalesInvoice.branch_id == branch_id,
            SalesInvoice.status.in_(_ACTIVE_SI), SalesInvoice.invoice_date <= as_of).all():
        paid = _crv_applied_to(as_of, invoice_id=i.id) + _cm_applied_to_si(i.id, as_of)
        remaining = Decimal(str(i.total_amount)) - paid
        if remaining > 0:
            buckets[_age_bucket(i.due_date or i.invoice_date, as_of)] += remaining

    for m in SalesMemo.query.filter(
            SalesMemo.customer_id == customer_id, SalesMemo.branch_id == branch_id,
            SalesMemo.memo_type == 'debit', SalesMemo.status == 'posted',
            SalesMemo.memo_date <= as_of).all():
        paid = _crv_applied_to(as_of, sales_memo_id=m.id)
        remaining = Decimal(str(m.total_amount)) - paid
        if remaining > 0:
            buckets[_age_bucket(m.memo_date, as_of)] += remaining

    buckets['total'] = sum(buckets.values(), Decimal('0.00'))
    return buckets


def build_statement_of_account(customer_id, branch_id, period):
    d_from, d_to = period['date_from'], period['date_to']
    events = _collect_events(customer_id, branch_id)

    opening = sum((e['charge'] - e['credit'] for e in events if e['date'] < d_from),
                  Decimal('0.00'))

    in_period = [e for e in events if d_from <= e['date'] <= d_to]
    in_period.sort(key=lambda e: (e['date'], _KIND_RANK[e['kind']], e['doc_number']))

    running = opening
    total_charges = Decimal('0.00')
    total_credits = Decimal('0.00')
    rows = []
    for e in in_period:
        running += e['charge'] - e['credit']
        total_charges += e['charge']
        total_credits += e['credit']
        rows.append({**e, 'running_balance': running})

    closing = opening + total_charges - total_credits
    aging = _age_open_items(customer_id, branch_id, d_to)
    return {'opening_balance': opening, 'rows': rows,
            'total_charges': total_charges, 'total_credits': total_credits,
            'closing_balance': closing, 'aging': aging}
