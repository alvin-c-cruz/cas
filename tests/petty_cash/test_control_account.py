"""Petty Cash Short/Over control account tests (R-04 slice 4)."""
import pytest
from app.posting.control_accounts import get_control_account, ControlAccountError, CONTROL_ACCOUNTS

pytestmark = [pytest.mark.integration]


def test_short_over_key_registered():
    assert 'petty_cash_short_over' in CONTROL_ACCOUNTS


def test_unassigned_raises_fail_closed(db_session):
    with pytest.raises(ControlAccountError):
        get_control_account('petty_cash_short_over')
