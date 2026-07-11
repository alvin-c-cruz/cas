import pytest
from app.accounts.models import Account
from app.settings import AppSettings
from app.posting.control_accounts import (
    get_control_account, ControlAccountError, assign_default_control_accounts,
)


def _acct(db_session, code, name='Ctrl', atype='Asset', nb='Debit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Asset', normal_balance=nb)
    db_session.add(a)
    db_session.commit()
    return a


class TestControlAccountResolver:
    def test_resolves_assigned_code(self, db_session):
        a = _acct(db_session, '1210', 'AR - Trade')
        AppSettings.set_setting('ar_trade_account_code', '1210', updated_by='t')
        assert get_control_account('ar_trade').id == a.id

    def test_unassigned_required_raises_friendly(self, db_session):
        with pytest.raises(ControlAccountError) as exc:
            get_control_account('ar_trade')
        assert 'Accounts Receivable control account' in str(exc.value)
        assert 'Company Settings' in str(exc.value)

    def test_unassigned_optional_returns_none(self, db_session):
        assert get_control_account('ar_trade', required=False) is None

    def test_assigned_code_missing_account_raises(self, db_session):
        AppSettings.set_setting('ar_trade_account_code', '9999', updated_by='t')
        with pytest.raises(ControlAccountError):
            get_control_account('ar_trade')

    def test_assigned_code_missing_account_optional_none(self, db_session):
        AppSettings.set_setting('ap_trade_account_code', '9999', updated_by='t')
        assert get_control_account('ap_trade', required=False) is None

    def test_assign_defaults_backfills_only_existing(self, db_session):
        _acct(db_session, '10201', 'AR - Trade')  # only AR exists
        assign_default_control_accounts()
        assert AppSettings.get_setting('ar_trade_account_code') == '10201'
        assert AppSettings.get_setting('ap_trade_account_code') is None

    def test_assign_defaults_skips_already_set(self, db_session):
        _acct(db_session, '10201', 'AR - Trade')
        AppSettings.set_setting('ar_trade_account_code', '1210', updated_by='t')
        assign_default_control_accounts()
        assert AppSettings.get_setting('ar_trade_account_code') == '1210'  # unchanged
