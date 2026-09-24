"""The CV form fills the check number, bank and check date for the chosen account.

Owner, 2026-09-24: "can we also auto increment check number field?" and "the two
bank fields should also autofill." A checkbook belongs to a bank ACCOUNT, so the
series is per cash/bank account: the account's highest check number so far plus
one, width kept ('0012345' -> '0012346'), skipping any serial that account already
holds on a live CDV (the same per-account uniqueness the save enforces). The bank
is the account's own bank_name from Bank Accounts, else the bank typed on that
account's last check. Everything is a suggestion; nothing typed is overwritten.
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app.cash_disbursements.models import CashDisbursementVoucher
from tests.integration.test_cdv_number_editable import login, setup_accounts, make_vendor

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


@pytest.fixture
def book(db_session, main_branch):
    """(cash account) plus put(check_number, bank='', status='posted', account=cash)."""
    _ap, _wt, cash, _exp = setup_accounts(db_session)
    vendor = make_vendor(db_session)
    n = iter(range(1, 999))

    def put(check_number, bank='', status='posted', account=None, method='check'):
        cdv = CashDisbursementVoucher(
            branch_id=main_branch.id, cdv_number='CK-%03d' % next(n), cdv_date=date(2026, 9, 24),
            vendor_id=vendor.id, vendor_name=vendor.name, payment_method=method,
            check_number=check_number, check_bank=bank, cash_account_id=(account or cash).id,
            status=status, total_amount=Decimal('1'))
        db_session.add(cdv); db_session.commit()
        return cdv
    put.cash = cash
    return put


def _next(account_id):
    from app.cash_disbursements.views import next_check_for_account
    return next_check_for_account(account_id)


class TestTheSeries:

    def test_no_check_yet_suggests_nothing(self, db_session, book):
        assert _next(book.cash.id)['check_number'] == ''

    def test_increments_keeping_width(self, db_session, book):
        book('0012345')
        assert _next(book.cash.id)['check_number'] == '0012346'

    def test_the_numeric_max_wins(self, db_session, book):
        book('000200'); book('000199')
        assert _next(book.cash.id)['check_number'] == '000201'

    def test_a_voided_serial_is_reused_not_skipped(self, db_session, book):
        """A voided check's serial is free again (test_cdv_check_serial pins that
        rule for the save); the suggestion must agree with the save."""
        book('000010', status='voided')
        book('000009')
        assert _next(book.cash.id)['check_number'] == '000010'

    def test_a_live_serial_is_skipped(self, db_session, book):
        book('000010'); book('000011'); book('000009')
        assert _next(book.cash.id)['check_number'] == '000012'

    def test_each_account_is_its_own_checkbook(self, db_session, book):
        from app.accounts.models import Account
        other = Account(code='10102', name='Cash in Bank 2', account_type='Asset',
                        normal_balance='debit', is_active=True)
        db_session.add(other); db_session.commit()
        book('0500'); book('0007', account=other)
        assert _next(other.id)['check_number'] == '0008'
        assert _next(book.cash.id)['check_number'] == '0501'

    def test_non_check_cdvs_do_not_count(self, db_session, book):
        book('9999', method='cash')       # a stray serial on a cash CDV
        book('0001')
        assert _next(book.cash.id)['check_number'] == '0002'

    def test_bank_comes_from_the_last_check_when_the_account_has_none(self, db_session, book):
        book('0001', bank='BDO')
        book('0002', bank='BPI')
        assert _next(book.cash.id)['bank'] == 'BPI'

    def test_bank_prefers_the_bank_accounts_record(self, db_session, book):
        from app.bank_accounts.models import BankAccount
        from app.branches.models import Branch
        db_session.add(BankAccount(branch_id=Branch.query.first().id, code='BDO-1',
                                   name='BDO Current', account_id=book.cash.id,
                                   bank_name='BDO Unibank'))
        db_session.commit()
        book('0001', bank='BPI')
        assert _next(book.cash.id)['bank'] == 'BDO Unibank'


class TestTheRoute:

    def _get(self, client, main_branch, account_id):
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        return client.get(f'/cash-disbursements/next-check?account_id={account_id}')

    def test_it_answers_json(self, client, db_session, admin_user, main_branch, book):
        book('0012345', bank='BDO')
        resp = self._get(client, main_branch, book.cash.id)
        assert resp.status_code == 200
        assert resp.get_json() == {'check_number': '0012346', 'bank': 'BDO'}

    def test_a_missing_account_is_empty_not_an_error(self, client, db_session, admin_user,
                                                     main_branch, book):
        resp = self._get(client, main_branch, 999999)
        assert resp.status_code == 200
        assert resp.get_json() == {'check_number': '', 'bank': ''}


def test_the_form_wires_the_autofill(client, db_session, admin_user, main_branch, book):
    """The JS that calls the route and fills the three fields is on the create form."""
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    html = client.get('/cash-disbursements/create').get_data(as_text=True)
    assert '/cash-disbursements/next-check' in html
    for field in ('check_number', 'check_bank', 'check_date'):
        assert re.search(r'getElementById\([\'"]%s[\'"]\)' % field, html), field
