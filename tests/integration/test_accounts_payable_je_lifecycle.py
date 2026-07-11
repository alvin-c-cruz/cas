"""JE lifecycle mirrors the APV lifecycle (B-018) and dashboard stats use
account types, not code prefixes (B-017).

- A draft APV's auto-created JE must be status='draft' so unposted vouchers
  never appear in GL-based reports
- Posting the APV promotes its JE to 'posted'
- get_expense_stats matches accounts by base_category='Expense', which covers
  all IS expense sub-types (Administrative Expense, Selling Expense, etc.);
  code prefixes are irrelevant — the type drives the bucket
"""
import json
from datetime import date

from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.journal_entries.models import JournalEntry
from app.dashboard.dashboard_data import get_expense_stats
from app.utils import ph_now
import pytest
pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]




def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def setup_gl(db_session):
    expense = Account(code='69902', name='JE Test Expense', account_type='Administrative Expense',
                      normal_balance='debit', is_active=True)
    ap = Account(code='20101', name='Accounts Payable - Trade',
                 account_type='Liability', normal_balance='credit', is_active=True)
    vendor = Vendor(code='JEV01', name='JE Vendor', check_payee_name='JE Vendor',
                    is_active=True)
    db_session.add_all([expense, ap, vendor])
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return expense, vendor


def create_draft(client, vendor, account):
    today = ph_now().date().isoformat()
    line_items = json.dumps([{'description': 'Item', 'amount': 1120.0,
                              'vat_category': '', 'account_id': account.id,
                              'wt_id': None, 'wt_rate': None}])
    return client.post('/accounts-payable/create', data={
        'ap_number': 'AP-JETEST-0001',
        'ap_date': today, 'due_date': today,
        'vendor_id': vendor.id, 'payment_terms': 'Net 30',
        'vendor_invoice_number': 'SI-001', 'vendor_invoice_date': today,
        'notes': 'Test particulars',
        'line_items': line_items,
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


class TestJELifecycle:
    def test_draft_bill_je_is_draft(self, client, db_session, admin_user, main_branch):
        login(client)
        expense, vendor = setup_gl(db_session)
        create_draft(client, vendor, expense)

        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
        assert bill is not None and bill.status == 'draft'
        je = db_session.get(JournalEntry, bill.journal_entry_id)
        assert je.status == 'draft'
        assert je.posted_at is None

    def test_posting_bill_promotes_je(self, client, db_session, admin_user, main_branch):
        login(client)
        expense, vendor = setup_gl(db_session)
        create_draft(client, vendor, expense)
        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()

        client.post(f'/accounts-payable/{bill.id}/post', follow_redirects=True)

        assert bill.status == 'posted'
        je = db_session.get(JournalEntry, bill.journal_entry_id)
        assert je.status == 'posted'
        assert je.posted_at is not None

    def test_expense_stats_match_by_type_and_exclude_drafts(self, client, db_session,
                                                            admin_user, main_branch):
        login(client)
        expense, vendor = setup_gl(db_session)
        create_draft(client, vendor, expense)
        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()

        now = ph_now()
        # while draft: nothing in expense stats
        stats = get_expense_stats(now.year, now.month, branch_id=main_branch.id)
        assert stats['mtd'] == 0.0

        # after posting: the expense account (6xxxx code) must be picked up
        client.post(f'/accounts-payable/{bill.id}/post', follow_redirects=True)
        stats = get_expense_stats(now.year, now.month, branch_id=main_branch.id)
        assert stats['mtd'] > 0
