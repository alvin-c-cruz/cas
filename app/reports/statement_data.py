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
    return {'opening_balance': opening, 'rows': rows,
            'total_charges': total_charges, 'total_credits': total_credits,
            'closing_balance': closing, 'aging': {}}
