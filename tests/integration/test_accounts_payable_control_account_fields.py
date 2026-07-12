import json
import pytest
from app import db
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def test_create_ap_persists_control_account_override(
        client, db_session, accountant_user, main_branch):
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    # _post_ap_je requires the GLOBAL ap_trade control account to be assigned
    # to post at all, independent of this task's per-transaction override field
    # (Task 7 wires the override into posting; this task only proves the form
    # captures + persists it). Mirrors the established pattern in
    # tests/integration/test_accounts_payable_je.py.
    default_ap_trade = Account(code='20101', name='Accounts Payable - Trade',
                               account_type='Liability', normal_balance='Credit', is_active=True)
    db.session.add(default_ap_trade); db.session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)

    ap_override = Account(code='APCF01', name='AP Trade Override', account_type='Liability',
                          normal_balance='Credit', is_active=True)
    expense_acct = Account(code='APCF02', name='Office Supplies', account_type='Expense',
                           normal_balance='Debit', is_active=True)
    db.session.add_all([ap_override, expense_acct]); db.session.commit()
    vendor = Vendor(code='APCFV1', name='Control Field Vendor', is_active=True)
    db.session.add(vendor); db.session.commit()

    line_items = json.dumps([{
        'description': 'Supplies', 'amount': 500.00, 'vat_category': '',
        'account_id': expense_acct.id, 'wt_id': None, 'wt_rate': None,
    }])
    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'APCF-0001', 'ap_date': '2026-07-12', 'due_date': '2026-08-11',
        'payee': f'vendor:{vendor.id}', 'payment_terms': 'Net 30',
        'ap_trade_account_id': str(ap_override.id), 'wht_payable_account_id': '',
        'notes': 'Test particulars',
        'line_items': line_items,
    }, follow_redirects=True)
    assert resp.status_code == 200

    ap = AccountsPayable.query.filter_by(ap_number='APCF-0001').first()
    assert ap is not None
    assert ap.ap_trade_account_id == ap_override.id
    assert ap.wht_payable_account_id is None
