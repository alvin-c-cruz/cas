"""Task 7: the manual admin Finalize lock is removed -- period-close + the
governed OpeningBalanceChangeRequest approval (Tasks 4-6) now do that job.

Reuses the login/branch-select/save/postable-leaf helpers already established in
tests/integration/test_opening_balances.py (mirrors test_opening_balance_gating.py).
"""
import pytest
from datetime import date

from app import db
from app.periods.models import AccountingPeriod
from app.opening_balances.utils import get_opening_entry, is_opening_locked

from tests.integration.test_opening_balances import (
    _login, _select_branch, _save_payload, _make_postable,
)

pytestmark = [pytest.mark.integration]


def test_finalize_route_is_gone(client, db_session, admin_user, main_branch):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/opening-balances/finalize', follow_redirects=True)
    assert resp.status_code == 404


def test_posted_entry_editable_while_period_open(client, db_session, admin_user, main_branch,
                                                  cash_account, revenue_account):
    """No manual Finalize action exists anymore -- a posted opening entry stays
    editable (via re-open) as long as its period is NOT closed."""
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ]))
    client.post('/opening-balances/post')
    assert get_opening_entry(main_branch.id).status == 'posted'

    assert is_opening_locked(main_branch.id) is False

    resp = client.post('/opening-balances/reopen', follow_redirects=True)
    assert get_opening_entry(main_branch.id).status == 'draft'
    assert resp.status_code == 200


def test_posted_entry_locked_once_period_closes(client, db_session, admin_user, main_branch,
                                                 cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ]))
    client.post('/opening-balances/post')
    assert is_opening_locked(main_branch.id) is False

    db.session.add(AccountingPeriod(year=2026, month=1, status='closed'))
    db.session.commit()

    assert is_opening_locked(main_branch.id) is True
    resp = client.post('/opening-balances/reopen', follow_redirects=True)
    assert get_opening_entry(main_branch.id).status == 'posted'  # unchanged, refused
    assert b'locked' in resp.data
