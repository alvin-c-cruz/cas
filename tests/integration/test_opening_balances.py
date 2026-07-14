import pytest
from app import db
from app.journals.views import VOUCHER_TYPES
from app.reports.general_journal_data import VOUCHER_ENTRY_TYPES
from app.users.module_access import MODULE_REGISTRY

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


def test_save_draft_refused_on_posted_entry(client, db_session, admin_user, main_branch,
                                            cash_account, revenue_account):
    """A POSTED opening can't be edited via Save — must be re-opened first (final-review fix).

    Guards against rebuilding a posted entry in place (which could push an unbalanced
    entry into the trial balance)."""
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    client.post('/opening-balances/post')
    assert get_opening_entry(main_branch.id).status == 'posted'

    # Try to edit the posted entry via Save with an (unbalanced) change — must be refused.
    resp = client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '5.00', '0'),
    ]), follow_redirects=True)
    entry = get_opening_entry(main_branch.id)
    assert entry.status == 'posted'              # unchanged
    assert float(entry.total_debit) == 1000.00   # lines NOT rebuilt
    assert b'Re-open' in resp.data


# ---------------------------------------------------------------------------
# Task 4: post_entry tests
# ---------------------------------------------------------------------------

from app.reports.financial import generate_trial_balance
from app.periods.models import AccountingPeriod


def _save_and_get(client, branch_id, cutover, lines):
    client.post('/opening-balances/save', data=_save_payload(cutover, lines))
    return get_opening_entry(branch_id)


def test_post_blocked_when_unbalanced(client, db_session, admin_user, main_branch,
                                      cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '700.00'),
    ])
    resp = client.post('/opening-balances/post', follow_redirects=True)
    assert get_opening_entry(main_branch.id).status == 'draft'
    assert b'must be balanced' in resp.data


def test_post_succeeds_and_appears_in_trial_balance(client, db_session, admin_user,
                                                    main_branch, cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    resp = client.post('/opening-balances/post', follow_redirects=True)
    assert get_opening_entry(main_branch.id).status == 'posted'

    tb = generate_trial_balance(as_of_date=date(2026, 12, 31), branch_id=main_branch.id)
    codes = {row['code'] for row in tb['accounts']}
    assert cash_account.code in codes
    # post is audited
    assert AuditLog.query.filter_by(module='opening_balances', action='post').first() is not None


def test_post_into_closed_period_refused(client, db_session, admin_user, main_branch,
                                         cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    db.session.add(AccountingPeriod(year=2026, month=1, status='closed'))
    db.session.commit()
    resp = client.post('/opening-balances/post', follow_redirects=True)
    assert get_opening_entry(main_branch.id).status == 'draft'
    assert b'locked' in resp.data


def test_post_with_no_period_row_succeeds_rvb4(client, db_session, admin_user, main_branch,
                                               cash_account, revenue_account):
    # No AccountingPeriod row for 2026-03 -> period is OPEN -> post allowed.
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-03-15', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    client.post('/opening-balances/post', follow_redirects=True)
    assert get_opening_entry(main_branch.id).status == 'posted'


def test_branch_isolation(client, db_session, admin_user, main_branch, branch_manila,
                          cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    client.post('/opening-balances/post', follow_redirects=True)
    assert get_opening_entry(branch_manila.id) is None


# ---------------------------------------------------------------------------
# Task 5: reopen tests
# ---------------------------------------------------------------------------

def _close_period(year, month):
    """Task 7: the manual finalize lock is gone -- these tests now lock the
    opening entry the real way, by closing its accounting period."""
    db.session.add(AccountingPeriod(year=year, month=month, status='closed'))
    db.session.commit()


def test_reopen_posted_entry_returns_to_draft(client, db_session, admin_user, main_branch,
                                              cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    client.post('/opening-balances/post')
    assert get_opening_entry(main_branch.id).status == 'posted'

    client.post('/opening-balances/reopen', follow_redirects=True)
    entry = get_opening_entry(main_branch.id)
    assert entry.status == 'draft'
    assert entry.posted_at is None


def test_reopen_refused_when_period_closed(client, db_session, admin_user, main_branch,
                                           cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    client.post('/opening-balances/post')
    _close_period(2026, 1)

    resp = client.post('/opening-balances/reopen', follow_redirects=True)
    assert get_opening_entry(main_branch.id).status == 'posted'  # unchanged
    assert b'locked' in resp.data


# ---------------------------------------------------------------------------
# Task 7: manual Finalize is removed -- period-close is the only lock left.
# ---------------------------------------------------------------------------

def test_free_edit_save_refused_once_period_closed(client, db_session, admin_user, main_branch,
                                                    cash_account, revenue_account):
    """No admin Finalize action exists anymore -- once the opening entry's period
    closes, the free-edit /save path is refused (the governed request-change path
    in test_opening_balance_gating.py is the only way to edit it from here)."""
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    client.post('/opening-balances/post')
    _close_period(2026, 1)

    resp = client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
        (cash_account.id, '5.00', '0'), (revenue_account.id, '0', '5.00'),
    ]), follow_redirects=True)
    assert b'locked' in resp.data
    assert float(get_opening_entry(main_branch.id).total_debit) == 1000.00  # unchanged


# ---------------------------------------------------------------------------
# Task 7: module registry + editor screen rendering
# ---------------------------------------------------------------------------

def test_opening_balances_in_module_registry_as_core():
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'opening_balances'), None)
    assert entry is not None
    assert entry.get('optional') is None  # core, always on
    assert entry['area'] == 'Accounting'
    assert 'opening_balances.' in entry['endpoints']


def test_index_renders_for_admin(client, db_session, admin_user, main_branch):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/opening-balances')
    assert resp.status_code == 200
    assert b'Opening Balances' in resp.data


def test_index_shows_locked_state(client, db_session, admin_user, main_branch,
                                  cash_account, revenue_account):
    _make_postable(db_session, cash_account, revenue_account)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    _save_and_get(client, main_branch.id, '2026-01-01', [
        (cash_account.id, '1000.00', '0'), (revenue_account.id, '0', '1000.00'),
    ])
    client.post('/opening-balances/post')
    _close_period(2026, 1)
    resp = client.get('/opening-balances')
    assert resp.status_code == 200
    assert b'Finalized' in resp.data or b'locked' in resp.data.lower()
