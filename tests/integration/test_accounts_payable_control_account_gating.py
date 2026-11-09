"""The AP Trade / WHT Payable account override on the APV: admin and chief accountant only (plan item
2.1; owner, 2 Nov 2026: "admin / chief accountant only, as on the SI"). The AP half of work order
2026-07-24-si-control-account-override-not-gated (the SI half was fixed in 4acde49b): hidden from
everyone else, a posted value from them ignored -- the company's control accounts on create, the
voucher's own accounts kept on edit."""
import json

import pytest

from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable
from app.vendors.models import Vendor

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration, pytest.mark.control_accounts]


def _account(code, name, atype='Liability', nb='Credit'):
    a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture
def book(db_session):
    """The company's control accounts (20101 AP Trade, 20301 WHT Payable), two override
    accounts, an expense account and a vendor."""
    from tests.conftest import assign_control_accounts
    default_ap = _account('20101', 'Accounts Payable - Trade')
    default_wt = _account('20301', 'WHT Payable')
    assign_control_accounts(db_session)
    return {
        'default_ap': default_ap, 'default_wt': default_wt,
        'ap': _account('APG01', 'AP Trade Override'), 'wt': _account('APG02', 'WHT Override'),
        'expense': _account('APG03', 'Office Supplies', 'Expense', 'Debit'),
        'vendor': _vendor(),
    }


def _vendor():
    v = Vendor(code='APGV1', name='Gating Vendor', is_active=True)
    db.session.add(v)
    db.session.commit()
    return v


def _login(client, username, password, branch):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _payload(book, number):
    return {
        'ap_number': number, 'ap_date': '2026-11-02', 'due_date': '2026-12-02',
        'payee': f'vendor:{book["vendor"].id}', 'payment_terms': 'Net 30', 'notes': 'Supplies',
        'ap_trade_account_id': str(book['ap'].id), 'wht_payable_account_id': str(book['wt'].id),
        'line_items': json.dumps([{'description': 'Supplies', 'amount': 500.00, 'vat_category': '',
                                   'account_id': book['expense'].id, 'wt_id': None, 'wt_rate': None}]),
    }


def _ap(number):
    db.session.expire_all()
    return AccountsPayable.query.filter_by(ap_number=number).first()


class TestTheForm:
    def test_an_accountant_does_not_see_the_override_boxes(self, client, accountant_user, main_branch, book):
        _login(client, 'accountant', 'accountant123', main_branch)
        body = client.get('/accounts-payable/create').get_data(as_text=True)
        assert 'name="payee"' in body or 'id="vendorCard"' in body        # the form is there
        assert 'name="ap_trade_account_id"' not in body
        assert 'name="wht_payable_account_id"' not in body

    def test_staff_do_not_see_them(self, client, db_session, staff_user, main_branch, book):
        staff_user.set_branches([main_branch]); db_session.commit()
        _login(client, 'staff', 'staff123', main_branch)
        body = client.get('/accounts-payable/create').get_data(as_text=True)
        assert 'name="ap_trade_account_id"' not in body and 'name="wht_payable_account_id"' not in body

    @pytest.mark.parametrize('username, password', [('admin', 'admin123'), ('chief', 'chief123')])
    def test_admin_and_chief_accountant_see_them(
            self, client, admin_user, chief_accountant_user, main_branch, book, username, password):
        _login(client, username, password, main_branch)
        body = client.get('/accounts-payable/create').get_data(as_text=True)
        assert 'name="ap_trade_account_id"' in body and 'name="wht_payable_account_id"' in body


class TestTheSave:
    def test_an_accountants_posted_override_is_ignored(self, client, accountant_user, main_branch, book):
        _login(client, 'accountant', 'accountant123', main_branch)
        client.post('/accounts-payable/create', data=_payload(book, 'APG-0001'), follow_redirects=True)
        ap = _ap('APG-0001')
        assert ap is not None
        assert (ap.ap_trade_account_id, ap.wht_payable_account_id) == (
            book['default_ap'].id, book['default_wt'].id)

    def test_the_admins_override_is_kept(self, client, admin_user, main_branch, book):
        _login(client, 'admin', 'admin123', main_branch)
        client.post('/accounts-payable/create', data=_payload(book, 'APG-0002'), follow_redirects=True)
        ap = _ap('APG-0002')
        assert (ap.ap_trade_account_id, ap.wht_payable_account_id) == (book['ap'].id, book['wt'].id)

    def test_an_accountants_edit_keeps_the_vouchers_accounts(self, client, accountant_user, main_branch, book):
        """An override set earlier by the admin survives an accountant's edit: not reset to the
        company default, not changed to what was posted."""
        _login(client, 'accountant', 'accountant123', main_branch)
        client.post('/accounts-payable/create', data=_payload(book, 'APG-0003'), follow_redirects=True)
        ap = _ap('APG-0003')
        ap.ap_trade_account_id, ap.wht_payable_account_id = book['ap'].id, book['wt'].id
        db.session.commit()
        other = _account('APG04', 'Another Override')
        data = _payload(book, 'APG-0003')
        data.update(ap_trade_account_id=str(other.id), wht_payable_account_id='', notes='edited',
                    row_version=str(ap.row_version))
        client.post(f'/accounts-payable/{ap.id}/edit', data=data, follow_redirects=True)
        ap = _ap('APG-0003')
        assert ap.notes == 'edited'                                         # the edit saved
        assert (ap.ap_trade_account_id, ap.wht_payable_account_id) == (book['ap'].id, book['wt'].id)
