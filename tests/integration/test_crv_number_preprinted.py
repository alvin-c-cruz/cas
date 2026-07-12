"""Cash Receipts use a PRE-PRINTED receipt number typed by the user (like Sales
Invoices), not an auto-generated sequence. These pin that the create/edit routes
persist the user-entered crv_number verbatim and reject duplicates with a friendly
message. See memory project-preprinted-document-numbers.
"""
import json

import pytest
from decimal import Decimal

from app.accounts.models import Account
from app.customers.models import Customer
from app.cash_receipts.models import CashReceiptVoucher
from app.utils import ph_now

pytestmark = [pytest.mark.integration]


def login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def setup_accounts(db_session):
    ar   = Account(code='10201', name='AR Trade',        account_type='Asset',  normal_balance='debit',  is_active=True)
    wt   = Account(code='10212', name='WHT Receivable',  account_type='Asset',  normal_balance='debit',  is_active=True)
    cash = Account(code='10101', name='Cash on Hand',    account_type='Asset',  normal_balance='debit',  is_active=True)
    rev  = Account(code='40101', name='Service Revenue', account_type='Income', normal_balance='credit', is_active=True)
    db_session.add_all([ar, wt, cash, rev])
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return ar, wt, cash, rev


def make_customer(db_session):
    c = Customer(code='CRV01', name='CRV Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def post_create(client, customer, cash, rev, crv_number):
    """POST the CR create route with a user-entered crv_number + one revenue line."""
    revenue_lines = [{'description': 'Service fee', 'amount': 1000.0,
                      'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
    return client.post('/cash-receipts/create', data={
        'crv_number': crv_number,
        'crv_date': ph_now().date().isoformat(),
        'customer_id': customer.id,
        'payment_method': 'cash',
        'cash_account_id': cash.id,
        'notes': 'Test CRV particulars',
        'ar_lines': json.dumps([]),
        'revenue_lines': json.dumps(revenue_lines),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


class TestPrePrintedCrvNumber:
    def test_create_persists_user_entered_number(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)

        # A pre-printed serial the accountant typed in — NOT a 5-digit auto-sequence.
        post_create(client, customer, cash, rev, crv_number='OR-5500123')

        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()
        assert crv is not None
        assert crv.crv_number == 'OR-5500123'

    def test_create_surfaces_a_fresh_suggestion_on_duplicate_number(
            self, client, db_session, admin_user, main_branch):
        """A duplicate is no longer a dead-end error (BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS
        fix, see test_cr_number_race.py) -- the form re-renders with a freshly suggested
        number instead, so the user can just Save again."""
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)

        post_create(client, customer, cash, rev, crv_number='OR-77')
        resp = post_create(client, customer, cash, rev, crv_number='OR-77')

        # Only the first one persisted; the duplicate is rejected, not 500.
        dupes = CashReceiptVoucher.query.filter_by(crv_number='OR-77').all()
        assert len(dupes) == 1
        assert resp.status_code == 200
        assert b'was just taken' in resp.data

    def test_edit_persists_changed_number(self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)

        post_create(client, customer, cash, rev, crv_number='OR-100')
        crv = CashReceiptVoucher.query.order_by(CashReceiptVoucher.id.desc()).first()

        client.post(f'/cash-receipts/{crv.id}/edit', data={
            'crv_number': 'OR-200',
            'crv_date': ph_now().date().isoformat(),
            'customer_id': customer.id,
            'payment_method': 'cash',
            'cash_account_id': cash.id,
            'notes': 'Edited particulars',
            'row_version': crv.row_version,
            'ar_lines': json.dumps([]),
            'revenue_lines': json.dumps([{'description': 'Service fee', 'amount': 1000.0,
                                          'vat_category': '', 'account_id': rev.id, 'wt_id': None}]),
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

        db_session.refresh(crv)
        assert crv.crv_number == 'OR-200'
