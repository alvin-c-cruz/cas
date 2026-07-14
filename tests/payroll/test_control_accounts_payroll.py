"""Payroll (R-06) control-account keys are fully accountant-assigned/dynamic.

No seed file or migration auto-assigns a code for any `payroll_*` key --
mirrors app/vat_settlement/service.py's `resolve_target_account` ("Fail-closed:
NO default code"). These tests pin that contract at the resolver level:
`CONTROL_ACCOUNTS` carries the keys, `DEFAULT_CONTROL_ACCOUNT_CODES` does not,
and `assign_default_control_accounts()` (the seed backfill helper) leaves them
untouched.
"""
import pytest
from app.accounts.models import Account
from app.settings import AppSettings
from app.posting.control_accounts import (
    CONTROL_ACCOUNTS, DEFAULT_CONTROL_ACCOUNT_CODES,
    get_control_account, ControlAccountError, assign_default_control_accounts,
)

PAYROLL_KEYS = [k for k in CONTROL_ACCOUNTS if k.startswith('payroll_')]


def _acct(db_session, code, name='Ctrl', atype='Asset', nb='Debit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Asset', normal_balance=nb)
    db_session.add(a)
    db_session.commit()
    return a


class TestPayrollControlAccountKeysRegistered:
    def test_all_eleven_payroll_keys_present(self):
        expected = {
            'payroll_salaries_expense', 'payroll_sss_er_expense',
            'payroll_philhealth_er_expense', 'payroll_pagibig_er_expense',
            'payroll_wht_payable', 'payroll_sss_payable',
            'payroll_philhealth_payable', 'payroll_pagibig_payable',
            'payroll_sss_loan_payable', 'payroll_pagibig_loan_payable',
            'payroll_accrued_salaries',
        }
        assert expected <= CONTROL_ACCOUNTS.keys()

    def test_no_payroll_key_has_a_seeded_default(self):
        """Load-bearing: proves nothing was silently added to the legacy-default
        dict alongside the CONTROL_ACCOUNTS registration."""
        payroll_defaults = {k for k in DEFAULT_CONTROL_ACCOUNT_CODES if k.startswith('payroll_')}
        assert payroll_defaults == set()


class TestPayrollControlAccountResolver:
    def test_unassigned_required_raises_control_account_error(self, db_session):
        with pytest.raises(ControlAccountError) as exc:
            get_control_account('payroll_accrued_salaries')
        assert 'Accrued Salaries and Wages control account' in str(exc.value)
        assert 'Company Settings' in str(exc.value)

    def test_unassigned_optional_returns_none(self, db_session):
        assert get_control_account('payroll_accrued_salaries', required=False) is None

    def test_resolves_once_accountant_assigns_it(self, db_session):
        # Simulates what an accountant does via the Company Settings ->
        # Control Accounts picker (app/company_settings/views.py::save_control_accounts).
        a = _acct(db_session, '20501', 'Accrued Salaries and Wages',
                  atype='Liability', nb='Credit')
        AppSettings.set_setting('payroll_accrued_salaries_account_code', '20501',
                                 updated_by='test')
        resolved = get_control_account('payroll_accrued_salaries')
        assert resolved.id == a.id
        assert resolved.code == '20501'

    def test_assigned_code_missing_account_raises(self, db_session):
        AppSettings.set_setting('payroll_wht_payable_account_code', '99999',
                                 updated_by='test')
        with pytest.raises(ControlAccountError):
            get_control_account('payroll_wht_payable')


class TestAssignDefaultsNeverTouchesPayrollKeys:
    """Regression: assign_default_control_accounts() is the seed-time backfill
    helper. It must remain a no-op for every payroll key, proving the
    'no seeded defaults anywhere' requirement holds even if a future seed
    script starts calling it against a chart that happens to contain accounts
    at the conceptual payroll codes (e.g. 20501)."""

    def test_regression_all_payroll_keys_stay_unset(self, db_session):
        # Seed accounts at codes that conceptually match several payroll keys,
        # to prove a coincidental code match still isn't auto-assigned.
        _acct(db_session, '50210', 'Salaries Expense', atype='Expense', nb='Debit')
        _acct(db_session, '20302', 'Withholding Tax on Compensation Payable',
              atype='Liability', nb='Credit')
        _acct(db_session, '20501', 'Accrued Salaries and Wages',
              atype='Liability', nb='Credit')

        assign_default_control_accounts()

        for key in PAYROLL_KEYS:
            setting_key, _ = CONTROL_ACCOUNTS[key]
            assert AppSettings.get_setting(setting_key) is None, (
                f'{setting_key} was auto-assigned by assign_default_control_accounts() '
                f'-- payroll control accounts must stay accountant-assigned only.'
            )

    def test_legacy_non_payroll_keys_still_backfill_unaffected(self, db_session):
        """Sanity: confirms the payroll additions didn't break the existing
        legacy-key backfill behavior for the original 4 keys."""
        _acct(db_session, '10201', 'AR - Trade')
        assign_default_control_accounts()
        assert AppSettings.get_setting('ar_trade_account_code') == '10201'
