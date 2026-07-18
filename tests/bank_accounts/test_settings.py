"""Tests for the cash/bank-parent setting + fail-soft leaf-account helper (R-04 slice 1)."""
import pytest
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def test_leaf_choices_filtered_to_parent(db_session, cash_account, revenue_account):
    from app.bank_accounts import service
    AppSettings.set_setting('cash_bank_parent_account_code', cash_account.code)
    db_session.commit()
    ids = {aid for aid, _ in service.cash_bank_leaf_account_choices()}
    assert cash_account.id in ids
    assert revenue_account.id not in ids


def test_leaf_choices_fail_soft_when_unassigned(db_session, cash_account, revenue_account):
    from app.bank_accounts import service
    AppSettings.set_setting('cash_bank_parent_account_code', '')   # unassigned
    db_session.commit()
    ids = {aid for aid, _ in service.cash_bank_leaf_account_choices()}
    assert revenue_account.id in ids              # falls back to ALL leaves
