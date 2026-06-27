import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.users.models import User

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Local fixtures (ar_account not in conftest; revenue_account is, but
# conftest uses 'Income' type — we add a test-local AR fixture here)
# ---------------------------------------------------------------------------

@pytest.fixture
def ar_account(db_session):
    a = Account(code='AR-T1', name='Accounts Receivable Test',
                account_type='Asset', normal_balance='debit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


# revenue_account already exists in conftest.py but use a local one to avoid
# clashes (conftest uses code='4001', type='Income').  We define a fresh one
# with a unique code so both can coexist.
@pytest.fixture
def revenue_account(db_session):
    a = Account(code='REV-T1', name='Revenue Test',
                account_type='Revenue', normal_balance='credit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, db_session, branch):
    """Create an accountant user, assign to branch, set session, and log in."""
    from app.users.module_access import default_all_permissions
    u = User(username='acct_si', email='acct_si@example.com',
             full_name='Acct SI', role='accountant', is_active=True)
    u.set_password('Passw0rd!si')
    # Accountants are now gated by book_permissions (Task 3); grant all so this
    # fixture user can reach /journals/si (accounts_receivable module).
    u.set_book_permissions(default_all_permissions())
    u.branches.append(branch)
    db.session.add(u)
    db.session.commit()
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch.id
    client.post('/login', data={'username': 'acct_si', 'password': 'Passw0rd!si'},
                follow_redirects=True)


def _si_entry(db_session, branch_id, status, entry_date, number, lines):
    """Create a JournalEntry with entry_type='sale' and given lines.
    lines = list of (account, debit_amount, credit_amount)
    """
    je = JournalEntry(
        entry_number=number, reference=number, entry_type='sale', entry_date=entry_date,
        description=f'SI {number}', status=status, branch_id=branch_id,
        total_debit=sum(d for _, d, _ in lines),
        total_credit=sum(c for _, _, c in lines),
    )
    db.session.add(je)
    db.session.flush()
    for i, (acct, dr, cr) in enumerate(lines, 1):
        db.session.add(JournalEntryLine(
            entry_id=je.id, account_id=acct.id, line_number=i,
            debit_amount=dr, credit_amount=cr, description='',
        ))
    je.is_balanced = True
    db.session.commit()
    return je


def _voided_si(db_session, branch_id, invoice_number, invoice_date,
               customer_name='Customer A'):
    """Create a voided SalesInvoice (no journal entry)."""
    from app.sales_invoices.models import SalesInvoice
    from app.customers.models import Customer

    # SalesInvoice.customer_id is NOT NULL so we need a real customer row.
    customer = Customer(code=f'CUST-{invoice_number}', name=customer_name)
    db.session.add(customer)
    db.session.flush()

    si = SalesInvoice(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=invoice_date,          # due_date is NOT NULL
        customer_id=customer.id,        # FK NOT NULL
        customer_name=customer_name,
        branch_id=branch_id,
        status='voided',
        subtotal=Decimal('0'),
        vat_amount=Decimal('0'),
        total_before_wt=Decimal('0'),   # NOT NULL in model
        withholding_tax_amount=Decimal('0'),
        total_amount=Decimal('0'),
        notes='',
    )
    db.session.add(si)
    db.session.commit()
    return si


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSIJournalViews:

    def test_si_journal_view_renders_account_columns(
            self, client, db_session, main_branch, ar_account, revenue_account):
        """One posted SI JE → account names appear in body, period label in body."""
        _login(client, db_session, main_branch)
        _si_entry(db_session, main_branch.id, 'posted', date(2026, 6, 1), 'SI-0001', [
            (ar_account, Decimal('1000'), Decimal('0')),
            (revenue_account, Decimal('0'), Decimal('1000')),
        ])
        resp = client.get('/journals/si?mode=month&year=2026&month=6')
        assert resp.status_code == 200
        assert ar_account.name.encode() in resp.data
        assert revenue_account.name.encode() in resp.data
        assert b'2026' in resp.data

    def test_si_journal_export_returns_xlsx(
            self, client, db_session, main_branch, ar_account, revenue_account):
        """One posted SI JE → export returns XLSX with correct Content-Type and filename."""
        _login(client, db_session, main_branch)
        _si_entry(db_session, main_branch.id, 'posted', date(2026, 6, 1), 'SI-0002', [
            (ar_account, Decimal('500'), Decimal('0')),
            (revenue_account, Decimal('0'), Decimal('500')),
        ])
        resp = client.get('/journals/si/export?mode=month&year=2026&month=6')
        assert resp.status_code == 200
        assert resp.content_type.startswith('application/vnd.openxmlformats')
        assert b'SI-Journal-2026-06.xlsx' in resp.headers.get('Content-Disposition', '').encode()

    def test_si_journal_view_shows_draft_indicator(
            self, client, db_session, main_branch, ar_account, revenue_account):
        """One draft SI JE → 'Draft' badge appears in body."""
        _login(client, db_session, main_branch)
        _si_entry(db_session, main_branch.id, 'draft', date(2026, 6, 2), 'SI-0003', [
            (ar_account, Decimal('200'), Decimal('0')),
            (revenue_account, Decimal('0'), Decimal('200')),
        ])
        resp = client.get('/journals/si?mode=month&year=2026&month=6')
        assert resp.status_code == 200
        assert b'Draft' in resp.data or b'draft' in resp.data

    def test_si_journal_view_shows_voided_invoice(
            self, client, db_session, main_branch):
        """One voided SI → its invoice_number and 'VOIDED' appear in body."""
        _login(client, db_session, main_branch)
        _voided_si(db_session, main_branch.id, 'SI-V001', date(2026, 6, 3))
        resp = client.get('/journals/si?mode=month&year=2026&month=6')
        assert resp.status_code == 200
        assert b'SI-V001' in resp.data
        assert b'VOIDED' in resp.data or b'voided' in resp.data

    def test_si_journal_print_renders(
            self, client, db_session, main_branch, ar_account, revenue_account):
        """One posted SI JE → print view returns 200 with 'SALES JOURNAL' in body."""
        _login(client, db_session, main_branch)
        _si_entry(db_session, main_branch.id, 'posted', date(2026, 6, 1), 'SI-0004', [
            (ar_account, Decimal('750'), Decimal('0')),
            (revenue_account, Decimal('0'), Decimal('750')),
        ])
        resp = client.get('/journals/si/print?mode=month&year=2026&month=6')
        assert resp.status_code == 200
        assert b'SALES JOURNAL' in resp.data
        assert b'SI-0004' in resp.data

    def test_si_journal_redirects_without_branch(
            self, client, db_session, accountant_user, branch_manila):
        """GET /journals/si with no branch in session → 302 redirect.

        accountant_user has main_branch assigned (conftest); adding branch_manila gives 2
        accessible branches so before_request cannot auto-select → it redirects instead.
        """
        accountant_user.branches.append(branch_manila)
        db_session.commit()
        client.post('/login', data={'username': 'accountant', 'password': 'accountant123'},
                    follow_redirects=True)
        with client.session_transaction() as s:
            s.pop('selected_branch_id', None)
        resp = client.get('/journals/si', follow_redirects=False)
        assert resp.status_code == 302

    def test_si_list_view_journal_button_links_to_si_journal(
            self, client, db_session, main_branch, accountant_user):
        """SI list page contains /journals/si link and no '(Soon)' text."""
        # accountant_user fixture already assigns main_branch (conftest); no append needed
        client.post('/login', data={'username': 'accountant', 'password': 'accountant123'},
                    follow_redirects=True)
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id
        resp = client.get('/sales-invoices')
        assert resp.status_code == 200
        assert b'/journals/si' in resp.data
        assert b'(Soon)' not in resp.data
