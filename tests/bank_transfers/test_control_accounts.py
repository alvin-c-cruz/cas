"""Tests for the inter-branch clearing-account control keys (R-04 slice 2)."""
import pytest
from app.posting.control_accounts import get_control_account, ControlAccountError, CONTROL_ACCOUNTS

pytestmark = [pytest.mark.integration]


def test_clearing_keys_registered():
    assert 'inter_branch_due_from' in CONTROL_ACCOUNTS
    assert 'inter_branch_due_to' in CONTROL_ACCOUNTS


def test_unassigned_due_from_raises_fail_closed(db_session):
    with pytest.raises(ControlAccountError):
        get_control_account('inter_branch_due_from')


def test_assigned_due_from_resolves(db_session):
    from app.accounts.models import Account
    from app.settings import AppSettings
    acct = Account(code='10215', name='Inter-branch Due from', account_type='Asset',
                   normal_balance='Debit', is_active=True)
    db_session.add(acct); db_session.commit()
    AppSettings.set_setting('inter_branch_due_from_account_code', '10215')
    db_session.commit()
    resolved = get_control_account('inter_branch_due_from')
    assert resolved.id == acct.id
