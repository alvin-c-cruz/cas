"""Server-side line-item validation for Accounts Payable create (FINDING-2/3).

AP already rejects non-positive amounts and non-postable accounts, so it is not
vulnerable to the SI zero-amount junk. These tests pin the two remaining gaps:
an empty line list, and a line with a blank description.
"""
import json
from datetime import date

import pytest

from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def _setup(db_session):
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Debit'),
        ('69903', 'Test Expense', 'Expense', 'Debit'),
    ]:
        db_session.add(Account(code=code, name=name, account_type=typ,
                               normal_balance=bal, is_active=True))
    db_session.commit()
    db_session.add(VATCategory(code='V12DG', name='Input Tax Domestic Goods', rate=12.00,
                               is_active=True,
                               input_vat_account_id=Account.query.filter_by(code='10502').first().id))
    vendor = Vendor(code='BKT01', name='Bucket Vendor', check_payee_name='Bucket Vendor', is_active=True)
    db_session.add(vendor)
    db_session.commit()
    return vendor, Account.query.filter_by(code='69903').first()


def _login(client, user, branch):
    client.post('/login', data={'username': user.username, 'password': 'admin123'},
                follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _post(client, vendor, lines):
    return client.post('/accounts-payable/create', data={
        'ap_number': 'AP-VAL-0001',
        'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'vendor_id': vendor.id, 'payment_terms': 'Net 30',
        'notes': 'Test particulars',
        'line_items': json.dumps(lines),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    })


def test_ap_create_rejects_empty_line_list(client, db_session, admin_user, main_branch):
    vendor, _ = _setup(db_session)
    _login(client, admin_user, main_branch)
    resp = _post(client, vendor, [])
    assert resp.status_code == 200          # re-render, not a 302 redirect
    assert AccountsPayable.query.count() == 0


def test_ap_create_rejects_blank_description_line(client, db_session, admin_user, main_branch):
    vendor, exp = _setup(db_session)
    _login(client, admin_user, main_branch)
    resp = _post(client, vendor, [
        {'description': '   ', 'amount': 2240.0, 'vat_category': 'V12DG',
         'account_id': exp.id, 'wt_id': None, 'wt_rate': None},
    ])
    assert resp.status_code == 200
    assert AccountsPayable.query.count() == 0


def test_ap_create_still_rejects_zero_amount_line(client, db_session, admin_user, main_branch):
    """Regression: the pre-existing amount>0 guard must remain."""
    vendor, exp = _setup(db_session)
    _login(client, admin_user, main_branch)
    resp = _post(client, vendor, [
        {'description': 'goods', 'amount': 0, 'vat_category': 'V12DG',
         'account_id': exp.id, 'wt_id': None, 'wt_rate': None},
    ])
    assert resp.status_code == 200
    assert AccountsPayable.query.count() == 0


def test_ap_create_accepts_valid_line(client, db_session, admin_user, main_branch):
    vendor, exp = _setup(db_session)
    _login(client, admin_user, main_branch)
    resp = _post(client, vendor, [
        {'description': 'goods', 'amount': 2240.0, 'vat_category': 'V12DG',
         'account_id': exp.id, 'wt_id': None, 'wt_rate': None},
    ])
    assert resp.status_code == 302
    assert AccountsPayable.query.count() == 1
