"""TDD: CDV number must be editable on create/edit (B-11 #1).

Pins:
  (a) A custom CD number typed on create persists verbatim.
  (b) A duplicate CD number is rejected with an error flash (no CDV created).
  (c) Blank/whitespace-only number is rejected.
  (d) Edit keeping the own number is not falsely blocked.
"""
import json

import pytest
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.cash_disbursements.models import CashDisbursementVoucher
from app.utils import ph_now

pytestmark = [pytest.mark.integration]


def login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def setup_accounts(db_session):
    ap   = Account(code='20101', name='AP Trade',       account_type='Liability', normal_balance='credit', is_active=True)
    wt   = Account(code='20301', name='WHT Payable',    account_type='Liability', normal_balance='credit', is_active=True)
    cash = Account(code='10101', name='Cash on Hand',   account_type='Asset',     normal_balance='debit',  is_active=True)
    exp  = Account(code='60101', name='Office Supplies', account_type='Expense',  normal_balance='debit',  is_active=True)
    db_session.add_all([ap, wt, cash, exp])
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return ap, wt, cash, exp


def make_vendor(db_session):
    v = Vendor(code='CDV01', name='CDV Vendor', check_payee_name='CDV Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def post_create(client, vendor, cash, exp, cdv_number):
    """POST the CDV create route with one expense line and the given cdv_number."""
    expense_lines = [{'description': 'Supplies', 'amount': 500.0,
                      'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
    return client.post('/cash-disbursements/create', data={
        'cdv_number': cdv_number,
        'cdv_date': ph_now().date().isoformat(),
        'vendor_id': vendor.id,
        'payment_method': 'cash',
        'cash_account_id': cash.id,
        'notes': 'Test CDV particulars',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps(expense_lines),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


def post_edit(client, cdv_id, vendor, cash, exp, cdv_number):
    """POST the CDV edit route with one expense line and the given cdv_number."""
    expense_lines = [{'description': 'Edited Supplies', 'amount': 600.0,
                      'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
    return client.post(f'/cash-disbursements/{cdv_id}/edit', data={
        'cdv_number': cdv_number,
        'cdv_date': ph_now().date().isoformat(),
        'vendor_id': vendor.id,
        'payment_method': 'cash',
        'cash_account_id': cash.id,
        'notes': 'Edited CDV particulars',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps(expense_lines),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


class TestCdvNumberEditable:
    def test_custom_cdv_number_persists_on_create(self, client, db_session, admin_user, main_branch):
        """(a) A typed custom CD number is stored verbatim — the server must NOT
        override it with the auto-generated sequence."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)

        resp = post_create(client, vendor, cash, exp, 'CD-CUSTOM-9999')
        assert resp.status_code == 200

        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
        assert cdv is not None, 'CDV was not created'
        assert cdv.cdv_number == 'CD-CUSTOM-9999', (
            f'Expected CD-CUSTOM-9999, got {cdv.cdv_number!r}')

    def test_duplicate_cdv_number_rejected_on_create(self, client, db_session, admin_user, main_branch):
        """(b) Submitting a CD number already used by another CDV must be rejected
        with an error flash and must not create a second record."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)

        # First create succeeds.
        post_create(client, vendor, cash, exp, 'CD-DUPE-001')
        assert CashDisbursementVoucher.query.filter_by(cdv_number='CD-DUPE-001').count() == 1

        # Second create with same number must be rejected.
        resp = post_create(client, vendor, cash, exp, 'CD-DUPE-001')
        assert resp.status_code == 200
        assert CashDisbursementVoucher.query.filter_by(cdv_number='CD-DUPE-001').count() == 1, \
            'Duplicate CDV must not be persisted'
        assert b'already in use' in resp.data, \
            'Response must contain the duplicate-number flash message'

    def test_blank_cdv_number_rejected(self, client, db_session, admin_user, main_branch):
        """(c) Submitting a blank CD number must be rejected — no CDV created."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)

        resp = post_create(client, vendor, cash, exp, '')
        assert resp.status_code == 200
        assert CashDisbursementVoucher.query.count() == 0, \
            'No CDV must be created when the number is blank'

    def test_edit_own_number_is_not_blocked(self, client, db_session, admin_user, main_branch):
        """(d) Editing a CDV and re-submitting with the same number must succeed —
        the uniqueness check must exclude self."""
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)

        # Create a CDV.
        post_create(client, vendor, cash, exp, 'CD-SELF-001')
        cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
        assert cdv is not None
        assert cdv.cdv_number == 'CD-SELF-001'

        # Edit keeping the same number — must NOT be rejected as a duplicate.
        resp = post_edit(client, cdv.id, vendor, cash, exp, 'CD-SELF-001')
        assert resp.status_code == 200
        assert b'already in use' not in resp.data, \
            'Edit with same number must not trigger the duplicate-number error'
        db_session.refresh(cdv)
        assert cdv.cdv_number == 'CD-SELF-001'
