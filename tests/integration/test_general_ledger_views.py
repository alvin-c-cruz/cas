from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.views import _attach_source_links
from app.sales_invoices.models import SalesInvoice
from app.reports.financial import generate_general_ledger  # noqa: E402

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


# ── View tests ────────────────────────────────────────────────────────────────

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _post_je(branch_id, account, contra, when, number):
    je = JournalEntry(entry_number=number, entry_date=when, description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True,
                      total_debit=Decimal('100'), total_credit=Decimal('100'))
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=account.id,
                                    debit_amount=Decimal('100'), credit_amount=Decimal('0'),
                                    description='dr'))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=contra.id,
                                    debit_amount=Decimal('0'), credit_amount=Decimal('100'),
                                    description='cr'))
    db.session.commit()
    return je


def test_general_ledger_requires_login(client):
    resp = client.get('/reports/general-ledger')
    assert resp.status_code in (302, 401)


def test_general_ledger_admin_renders(client, db_session, main_branch, admin_user,
                                      cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-T1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger')
    assert resp.status_code == 200
    assert b'General Ledger' in resp.data
    assert cash_account.code.encode() in resp.data


def test_general_ledger_account_filter(client, db_session, main_branch, admin_user,
                                       cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-T2')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/reports/general-ledger?account_id={cash_account.id}')
    assert resp.status_code == 200
    assert cash_account.code.encode() in resp.data
    assert revenue_account.code.encode() not in resp.data


def test_general_ledger_staff_without_grant_denied(client, db_session, main_branch,
                                                   staff_user):
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger', follow_redirects=False)
    assert resp.status_code == 302  # global module gate redirects ungranted staff
