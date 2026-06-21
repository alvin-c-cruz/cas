from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.views import _attach_source_links
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.integration]


def test_attach_source_links_sale_links_to_invoice(db_session, main_branch, admin_user):
    # SalesInvoice requires customer_id (NOT NULL FK) and due_date (NOT NULL)
    customer = Customer(code='C001', name='ACME Corp')
    db.session.add(customer)
    db.session.flush()  # get customer.id before using it

    inv = SalesInvoice(invoice_number='SI-2026-06-0001', customer_name='ACME',
                       invoice_date=date(2026, 6, 5), due_date=date(2026, 7, 5),
                       customer_id=customer.id,
                       branch_id=main_branch.id,
                       status='posted', subtotal=Decimal('100'), total_amount=Decimal('100'),
                       balance=Decimal('0'))
    db.session.add(inv)
    db.session.commit()
    ledger = {'accounts': [{'lines': [
        {'entry_id': 1, 'entry_number': 'SI-0001', 'entry_type': 'sale',
         'reference': 'SI-2026-06-0001'},
        {'entry_id': 2, 'entry_number': 'JV-0007', 'entry_type': 'adjustment',
         'reference': 'JV-0007'},
    ]}]}
    _attach_source_links(ledger, main_branch.id)
    lines = ledger['accounts'][0]['lines']
    assert f'/sales-invoices/{inv.id}' in lines[0]['source']['url']
    assert lines[0]['source']['label'] == 'SI SI-2026-06-0001'
    # manual voucher falls back to the JE view
    assert '/journal-entries/2' in lines[1]['source']['url']
    assert lines[1]['source']['label'] == 'JV-0007'
