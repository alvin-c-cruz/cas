import pytest
from app import db
from app.journals.views import VOUCHER_TYPES
from app.reports.general_journal_data import VOUCHER_ENTRY_TYPES

pytestmark = [pytest.mark.integration]


def test_opening_balance_is_a_registered_voucher_type():
    assert 'opening_balance' in VOUCHER_TYPES
    assert 'opening_balance' in VOUCHER_ENTRY_TYPES


from datetime import date
from app.journal_entries.models import JournalEntry
from app.opening_balances.utils import get_opening_entry
from app.audit.models import AuditLog
from app.accounts.models import Account


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _save_payload(cutover, lines):
    """lines: list of (account_id, debit, credit) strings."""
    data = {'cutover_date': cutover}
    data['account_id'] = [str(a) for a, _, _ in lines]
    data['debit'] = [str(d) for _, d, _ in lines]
    data['credit'] = [str(c) for _, _, c in lines]
    return data


def _make_postable(db_session, *accounts):
    """Give each account a parent so it qualifies as a leaf (postable) account.

    The COA leaf rule: an account is postable only when it has a parent AND no
    children. Conftest fixtures create top-level accounts (no parent_id), which
    the rule treats as group headers. This helper inserts minimal parent rows so
    the opening-balances tests can submit real lines without hitting the group guard.
    """
    for acct in accounts:
        parent = Account(
            code=f'GRP-{acct.code}',
            name=f'{acct.name} Group',
            account_type=acct.account_type,
            normal_balance=acct.normal_balance,
            is_active=True,
        )
        db_session.add(parent)
        db_session.flush()
        acct.parent_id = parent.id
    db_session.commit()


def test_save_draft_creates_opening_entry(client, db_session, admin_user, main_branch,
                                          cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    payload = _save_payload('2026-01-01', [
        (cash_account.id, '1000.00', '0'),
        (revenue_account.id, '0', '1000.00'),
    ])
    resp = client.post('/opening-balances/save', data=payload, follow_redirects=False)
    assert resp.status_code == 302

    entry = get_opening_entry(main_branch.id)
    assert entry is not None
    assert entry.entry_type == 'opening_balance'
    assert entry.status == 'draft'
    assert entry.reference == 'OPENING BALANCES'
    assert entry.entry_date == date(2026, 1, 1)
    assert entry.lines.count() == 2
    assert float(entry.total_debit) == 1000.00
    assert float(entry.total_credit) == 1000.00
    audit = AuditLog.query.filter_by(module='opening_balances').first()
    assert audit is not None


def test_save_draft_replaces_lines_no_orphans(client, db_session, admin_user, main_branch,
                                              cash_account, revenue_account, expense_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '500.00', '0'), (revenue_account.id, '0', '500.00'),
    ]))
    client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '900.00', '0'), (revenue_account.id, '0', '900.00'),
    ]))
    entry = get_opening_entry(main_branch.id)
    assert entry.lines.count() == 2  # not 4 — old lines were deleted
    assert float(entry.total_debit) == 900.00
    # the entry is still the single active opening JE for the branch
    assert JournalEntry.query.filter_by(
        entry_type='opening_balance', branch_id=main_branch.id).count() == 1


def test_save_draft_rejects_group_account(client, db_session, admin_user, main_branch,
                                          cash_account, revenue_account):
    # Create a parent (group) account; cash_account becomes its child (leaf).
    # revenue_account also needs a parent to be postable.
    parent = Account(code='1000', name='Assets', account_type='Asset',
                     normal_balance='Debit', is_active=True)
    db.session.add(parent)
    db.session.commit()
    cash_account.parent_id = parent.id
    _make_postable(db_session, revenue_account)
    db.session.commit()

    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (parent.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ]), follow_redirects=True)
    assert get_opening_entry(main_branch.id) is None  # nothing saved
    assert b'postable account' in resp.data


def test_save_draft_blocked_for_viewer(client, db_session, viewer_user, main_branch,
                                       cash_account, revenue_account):
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ]), follow_redirects=False)
    assert resp.status_code == 302  # bounced by role guard
    assert get_opening_entry(main_branch.id) is None
