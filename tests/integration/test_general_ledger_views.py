from datetime import date
from decimal import Decimal
import pytest

from app import db
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
    # Post activity to both accounts (one JE debits cash, credits revenue).
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-T2')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/reports/general-ledger?account_id={cash_account.id}')
    assert resp.status_code == 200
    assert cash_account.code.encode() in resp.data
    # Only the filtered account's ledger section is rendered; each section has exactly
    # one "Opening balance" row — so the count must be 1, not 2.
    assert resp.data.count(b'Opening balance') == 1


def test_general_ledger_staff_without_grant_denied(client, db_session, main_branch,
                                                   staff_user):
    # Give staff access to the branch so the branch-validation hook doesn't redirect first.
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger', follow_redirects=False)
    # The module gate (not the branch hook) redirects ungranted staff.
    assert resp.status_code == 302
    assert resp.status_code != 200


def test_general_ledger_staff_with_grant_allowed(client, db_session, main_branch,
                                                  staff_user, cash_account, revenue_account):
    # Grant the general_ledger book permission.
    perms = staff_user.get_book_permissions()
    perms['general_ledger'] = True
    staff_user.set_book_permissions(perms)
    # Give staff access to the branch.
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger', follow_redirects=False)
    assert resp.status_code == 200


def test_general_ledger_excel_export(client, db_session, main_branch, admin_user,
                                     cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-E1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/export/excel?start_date=2026-06-01&end_date=2026-06-30')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']


def test_general_ledger_csv_export(client, db_session, main_branch, admin_user,
                                   cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-E2')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/export/csv')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers['Content-Type']


def test_general_ledger_print_renders(client, db_session, main_branch, admin_user,
                                      cash_account, revenue_account):
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-P1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/print')
    assert resp.status_code == 200
    assert b'General Ledger' in resp.data


def test_general_ledger_csv_export_contains_data(client, db_session, main_branch, admin_user,
                                                  cash_account, revenue_account):
    """_flatten_ledger rows (account header + Opening balance label) appear in the CSV body."""
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-CSV')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    today = date.today()
    start = date(today.year, today.month, 1).isoformat()
    end = today.isoformat()
    resp = client.get(f'/reports/general-ledger/export/csv?start_date={start}&end_date={end}')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers['Content-Type']
    # _flatten_ledger emits one header row per account (contains the code) and one row
    # with 'Opening balance' as the particulars column; verify both land in the file.
    assert cash_account.code.encode() in resp.data
    assert b'Opening balance' in resp.data
