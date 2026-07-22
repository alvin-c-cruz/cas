import pytest
from app.accounts.models import Account
from app.settings import AppSettings
from app.posting.control_accounts import (
    get_control_account, ControlAccountError, assign_default_control_accounts,
    get_postable_accounts, CONTROL_ACCOUNTS, CONTROL_ACCOUNT_MODULE_GATE,
    visible_control_accounts,
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


def _set_module(key, enabled):
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting(f'module_enabled:{key}', '1' if enabled else '0')
    clear_module_config_cache()


class TestVisibleControlAccounts:
    """Regression (BUG-CONTROL-ACCOUNTS-NO-MODULE-GATING)."""

    def test_core_keys_always_visible_regardless_of_any_module_state(self, db_session):
        _set_module('payroll', False)
        visible = visible_control_accounts()
        for key in ('ar_trade', 'ap_trade', 'creditable_wht', 'wht_payable'):
            assert key in visible

    def test_gated_key_hidden_when_owning_module_disabled(self, db_session):
        _set_module('payroll', False)
        visible = visible_control_accounts()
        assert 'payroll_salaries_expense' not in visible

    def test_gated_key_shown_when_owning_module_enabled(self, db_session):
        _set_module('payroll', True)
        visible = visible_control_accounts()
        assert 'payroll_salaries_expense' in visible

    def test_every_gated_key_exists_in_control_accounts(self):
        """CONTROL_ACCOUNT_MODULE_GATE keys must be a subset of CONTROL_ACCOUNTS --
        a typo'd key here would silently never gate anything."""
        assert set(CONTROL_ACCOUNT_MODULE_GATE) <= set(CONTROL_ACCOUNTS)

    def test_ungated_core_keys_always_visible_when_all_modules_disabled(self, db_session):
        """The 4 core keys are the ONLY ones absent from CONTROL_ACCOUNT_MODULE_GATE --
        every other key belongs to some optional module and IS gated. With every
        optional module disabled, only the 4 core keys should remain visible."""
        for key in ('payroll', 'bank_transfers', 'fixed_asset_disposal', 'petty_cash',
                    'inventory', 'bill_of_materials'):
            _set_module(key, False)
        visible = visible_control_accounts()
        assert set(visible) == {'ar_trade', 'ap_trade', 'creditable_wht', 'wht_payable'}


def test_get_postable_accounts_excludes_group_headers(db_session):
    parent = Account(code='PA001', name='Parent Group', account_type='Asset',
                     normal_balance='Debit')
    db_session.add(parent)
    db_session.commit()
    child = Account(code='PA002', name='Child Leaf', account_type='Asset',
                    normal_balance='Debit', parent_id=parent.id)
    db_session.add(child)
    db_session.commit()
    postable = get_postable_accounts()
    codes = {a.code for a in postable}
    assert 'PA002' in codes
    assert 'PA001' not in codes  # has children -> group header, not postable
