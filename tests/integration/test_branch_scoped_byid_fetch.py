"""By-id routes on branch-scoped masters must not serve another branch's record.

BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED: the LIST route filters on
`session['selected_branch_id']`, the by-id fetch does not, so a user on branch A
can GET/POST branch B's record by typing its URL. `before_request` validates the
SELECTED branch is accessible; it never checks the FETCHED record's branch.

Scope of THIS file: the "selected_branch_id" shape only -- work_centers,
bank_accounts, petty_cash. The `accessible_ids` modules (fixed_assets,
fixed_asset_depreciation, withholding_certificates) need a different guard (a
set-membership check, not single-branch equality) and `employees` needs an owner
decision about its list first; both are deliberately out of scope here.

Every test issues a REAL request. A unit assertion on the query object would
pass against the vulnerable code, because it never exercises the route's own
lookup -- which is the whole defect.

Petty cash note: PettyCashVoucher and PettyCashReplenishment carry NO branch_id
of their own; they inherit the branch through fund_id, so their guard must go
through the fund.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.bank_accounts.models import BankAccount
from app.petty_cash.models import (PettyCashFund, PettyCashReplenishment,
                                   PettyCashVoucher)
from app.settings import AppSettings
from app.work_centers.models import WorkCenter

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _enable_modules(db_session):
    """All three modules are `default_enabled: False`.

    Without this the module gate 404s every route here, and the cross-branch
    assertions pass VACUOUSLY -- they would go green against the vulnerable
    code, proving nothing. The control tests below are what exposed that: they
    showed OWN-branch access 404ing too. (memory feedback-outer-gate-masks-inner-guard)
    """
    for key in ('work_centers', 'bank_accounts', 'petty_cash'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')


def _login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


@pytest.fixture
def other_branch_work_center(db_session, branch_manila):
    wc = WorkCenter(branch_id=branch_manila.id, code='WC-OTHER',
                    name='Other Branch Work Center', hourly_rate=Decimal('10.00'),
                    is_active=True)
    db_session.add(wc)
    db_session.commit()
    return wc


@pytest.fixture
def other_branch_bank_account(db_session, branch_manila, make_account):
    acct = make_account('1099')
    ba = BankAccount(branch_id=branch_manila.id, code='BA-OTHER',
                     name='Other Branch Bank', account_id=acct.id,
                     opening_balance=Decimal('0.00'), is_active=True)
    db_session.add(ba)
    db_session.commit()
    return ba


@pytest.fixture
def other_branch_fund(db_session, branch_manila, make_account):
    acct = make_account('1098')
    fund = PettyCashFund(branch_id=branch_manila.id, code='PC-OTHER',
                         name='Other Branch Fund', account_id=acct.id,
                         float_amount=Decimal('5000.00'), status='active',
                         is_active=True)
    db_session.add(fund)
    db_session.commit()
    return fund


@pytest.fixture
def other_branch_voucher(db_session, other_branch_fund, make_account):
    exp = make_account('6099')
    v = PettyCashVoucher(fund_id=other_branch_fund.id, voucher_number='PCV-OTHER-1',
                         voucher_date=date(2026, 1, 5), payee='Someone',
                         expense_account_id=exp.id, amount=Decimal('100.00'),
                         status='held')
    db_session.add(v)
    db_session.commit()
    return v


@pytest.fixture
def other_branch_replenishment(db_session, other_branch_fund):
    r = PettyCashReplenishment(
        fund_id=other_branch_fund.id, replenishment_number='PCR-OTHER-1',
        replenishment_date=date(2026, 1, 6),
        physical_cash_counted=Decimal('4900.00'), vouchers_total=Decimal('100.00'),
        short_over_amount=Decimal('0.00'), replenish_amount=Decimal('100.00'),
        status='draft')
    db_session.add(r)
    db_session.commit()
    return r


def _assert_denied(response, what):
    """The record must not be served: 404, the shape first_or_404() produces.

    Deliberately does NOT accept a 3xx. An earlier version treated any redirect
    as "a refusal", which made these tests unable to fail: with the guard
    removed, fund_close still redirects -- but because post_close() raised
    ControlAccountError, nothing to do with the branch boundary. Accepting 302
    let a vulnerable route look guarded. Proved by mutation.
    """
    assert response.status_code == 404, (
        "%s was not refused across the branch boundary (status %s)"
        % (what, response.status_code))


class TestWorkCenters:

    def test_edit_get_does_not_serve_another_branchs_record(
            self, client, admin_user, main_branch, other_branch_work_center):
        _login(client)
        _select_branch(client, main_branch.id)
        r = client.get('/work-centers/%d/edit' % other_branch_work_center.id)
        _assert_denied(r, 'work center edit GET')

    def test_edit_post_does_not_write_another_branchs_record(
            self, client, db_session, admin_user, main_branch, other_branch_work_center):
        _login(client)
        _select_branch(client, main_branch.id)
        wc_id = other_branch_work_center.id
        client.post('/work-centers/%d/edit' % wc_id,
                    data={'code': 'HACKED', 'name': 'Hacked', 'hourly_rate': '99.00',
                          'is_active': '1'},
                    follow_redirects=True)
        db_session.expire_all()
        after = db_session.get(WorkCenter, wc_id)
        assert after.code == 'WC-OTHER', 'cross-branch POST mutated the record'
        assert after.name == 'Other Branch Work Center'

    def test_control_own_branch_edit_still_works(
            self, client, db_session, admin_user, main_branch):
        """The guard must not break the legitimate path."""
        wc = WorkCenter(branch_id=main_branch.id, code='WC-MINE', name='Mine',
                        hourly_rate=Decimal('1.00'), is_active=True)
        db_session.add(wc)
        db_session.commit()
        _login(client)
        _select_branch(client, main_branch.id)
        assert client.get('/work-centers/%d/edit' % wc.id).status_code == 200


class TestBankAccounts:

    def test_edit_get_does_not_serve_another_branchs_record(
            self, client, admin_user, main_branch, other_branch_bank_account):
        _login(client)
        _select_branch(client, main_branch.id)
        r = client.get('/bank-accounts/%d/edit' % other_branch_bank_account.id)
        _assert_denied(r, 'bank account edit GET')

    def test_toggle_active_does_not_flip_another_branchs_record(
            self, client, db_session, admin_user, main_branch, other_branch_bank_account):
        _login(client)
        _select_branch(client, main_branch.id)
        ba_id = other_branch_bank_account.id
        before = other_branch_bank_account.is_active
        client.post('/bank-accounts/%d/toggle-active' % ba_id, follow_redirects=True)
        db_session.expire_all()
        assert db_session.get(BankAccount, ba_id).is_active == before, (
            'cross-branch POST flipped is_active')

    def test_control_own_branch_edit_still_works(
            self, client, db_session, admin_user, main_branch, make_account):
        acct = make_account('1097')
        ba = BankAccount(branch_id=main_branch.id, code='BA-MINE', name='Mine',
                         account_id=acct.id, opening_balance=Decimal('0.00'),
                         is_active=True)
        db_session.add(ba)
        db_session.commit()
        _login(client)
        _select_branch(client, main_branch.id)
        assert client.get('/bank-accounts/%d/edit' % ba.id).status_code == 200


class TestPettyCash:
    """9 routes, and the most exposed of the set -- money movement, not master data."""

    def test_fund_edit_does_not_serve_another_branchs_fund(
            self, client, admin_user, main_branch, other_branch_fund):
        _login(client)
        _select_branch(client, main_branch.id)
        _assert_denied(client.get('/petty-cash/funds/%d/edit' % other_branch_fund.id),
                       'petty cash fund edit')

    def test_fund_status_does_not_serve_another_branchs_fund(
            self, client, admin_user, main_branch, other_branch_fund):
        _login(client)
        _select_branch(client, main_branch.id)
        _assert_denied(client.get('/petty-cash/funds/%d' % other_branch_fund.id),
                       'petty cash fund status')

    def test_fund_close_does_not_reach_another_branchs_fund(
            self, client, db_session, admin_user, main_branch, other_branch_fund):
        """Assert the REFUSAL, not the side effect.

        An earlier version asserted only that status stayed 'active' -- and that
        passed even with the branch guard removed, because post_close() raises
        ControlAccountError in this fixture set (no control accounts configured)
        and rolls back. The fund survived for a reason that had nothing to do
        with the boundary under test. Proved vacuous by mutation: neutering
        _get_scoped_fund left the old assertion green.
        """
        _login(client)
        _select_branch(client, main_branch.id)
        fund_id = other_branch_fund.id
        r = client.post('/petty-cash/funds/%d/close' % fund_id)
        _assert_denied(r, 'petty cash fund close')
        db_session.expire_all()
        assert db_session.get(PettyCashFund, fund_id).status == 'active'

    def test_voucher_new_against_another_branchs_fund_is_refused(
            self, client, admin_user, main_branch, other_branch_fund):
        _login(client)
        _select_branch(client, main_branch.id)
        _assert_denied(
            client.get('/petty-cash/funds/%d/vouchers/new' % other_branch_fund.id),
            'voucher new against an off-branch fund')

    def test_voucher_edit_does_not_serve_another_branchs_voucher(
            self, client, admin_user, main_branch, other_branch_voucher):
        """Vouchers carry no branch_id -- the guard must go through fund.branch_id."""
        _login(client)
        _select_branch(client, main_branch.id)
        _assert_denied(client.get('/petty-cash/vouchers/%d/edit' % other_branch_voucher.id),
                       'voucher edit')

    def test_voucher_delete_does_not_delete_another_branchs_voucher(
            self, client, db_session, admin_user, main_branch, other_branch_voucher):
        _login(client)
        _select_branch(client, main_branch.id)
        v_id = other_branch_voucher.id
        client.post('/petty-cash/vouchers/%d/delete' % v_id, follow_redirects=True)
        db_session.expire_all()
        assert db_session.get(PettyCashVoucher, v_id) is not None, (
            'cross-branch POST deleted the voucher')

    def test_replenish_new_against_another_branchs_fund_is_refused(
            self, client, admin_user, main_branch, other_branch_fund):
        _login(client)
        _select_branch(client, main_branch.id)
        _assert_denied(
            client.get('/petty-cash/funds/%d/replenish' % other_branch_fund.id),
            'replenish against an off-branch fund')

    def test_replenish_detail_does_not_serve_another_branchs_record(
            self, client, admin_user, main_branch, other_branch_replenishment):
        _login(client)
        _select_branch(client, main_branch.id)
        _assert_denied(
            client.get('/petty-cash/replenishments/%d' % other_branch_replenishment.id),
            'replenishment detail')

    def test_replenish_print_does_not_serve_another_branchs_record(
            self, client, admin_user, main_branch, other_branch_replenishment):
        _login(client)
        _select_branch(client, main_branch.id)
        _assert_denied(
            client.get('/petty-cash/replenishments/%d/print' % other_branch_replenishment.id),
            'replenishment print')

    def test_control_own_branch_fund_still_reachable(
            self, client, db_session, admin_user, main_branch, make_account):
        acct = make_account('1096')
        fund = PettyCashFund(branch_id=main_branch.id, code='PC-MINE', name='Mine',
                             account_id=acct.id, float_amount=Decimal('1000.00'),
                             status='active', is_active=True)
        db_session.add(fund)
        db_session.commit()
        _login(client)
        _select_branch(client, main_branch.id)
        assert client.get('/petty-cash/funds/%d/edit' % fund.id).status_code == 200
