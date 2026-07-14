"""Task 4: governed change-request gating once the opening entry's period is closed.

Reuses the login/branch-select/save/postable-leaf helpers already established in
tests/integration/test_opening_balances.py (and mirrored by
test_opening_balances_acceptance.py) rather than inventing a new pattern.
"""
import pytest
from datetime import date

from app import db
from app.periods.models import AccountingPeriod
from app.opening_balances.utils import get_opening_entry
from app.opening_balances.approval_models import OpeningBalanceChangeRequest
from app.audit.models import AuditLog

from tests.integration.test_opening_balances import (
    _login, _select_branch, _save_payload, _make_postable,
)

pytestmark = [pytest.mark.integration]


def _post_line_form(cutover, account_id):
    return {'cutover_date': cutover, 'account_id': [str(account_id), str(account_id)],
            'debit': ['100.00', '0'], 'credit': ['0', '100.00']}


@pytest.mark.integration
class TestOpeningBalanceGating:

    def test_before_close_free_edit_no_request(self, client, db_session, db_with_data,
                                                accountant_user):
        """No period closed -> /opening-balances/save (free edit) works and creates
        NO OpeningBalanceChangeRequest -- the governed path only engages once locked."""
        cash = db_with_data['cash']
        revenue = db_with_data['revenue']
        branch = db_with_data['branch']
        _make_postable(db_session, cash, revenue)

        _login(client, accountant_user)
        _select_branch(client, branch.id)

        resp = client.post('/opening-balances/save',
                           data=_post_line_form('2026-06-01', cash.id),
                           follow_redirects=True)
        assert resp.status_code == 200

        entry = get_opening_entry(branch.id)
        assert entry is not None
        assert entry.status == 'draft'
        assert entry.entry_date == date(2026, 6, 1)
        assert OpeningBalanceChangeRequest.query.count() == 0

    def test_after_close_edit_creates_request(self, client, db_session, db_with_data,
                                              accountant_user):
        """Post + balance an opening entry dated 2026-01-01, CLOSE Jan 2026, then
        submit a change via /opening-balances/request-change -> a governed
        OpeningBalanceChangeRequest is created (and audited), not a silent edit."""
        cash = db_with_data['cash']
        revenue = db_with_data['revenue']
        branch = db_with_data['branch']
        _make_postable(db_session, cash, revenue)

        _login(client, accountant_user)
        _select_branch(client, branch.id)

        client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
            (cash.id, '1000.00', '0'), (revenue.id, '0', '1000.00'),
        ]))
        client.post('/opening-balances/post')
        assert get_opening_entry(branch.id).status == 'posted'

        AccountingPeriod.get_or_create_period(2026, 1).status = 'closed'
        db.session.commit()

        resp = client.post('/opening-balances/request-change',
                           data=_post_line_form('2026-01-01', cash.id),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert OpeningBalanceChangeRequest.query.count() == 1

        req = OpeningBalanceChangeRequest.query.first()
        assert req.branch_id == branch.id
        assert req.requested_by == accountant_user.username

        # Verify the audit log per CLAUDE.md convention: sole-accountant auto-approve
        # logs action='update' on the entry; a would-be-pending request logs
        # action='request'. With only one accountant/CA fixtured, this auto-approves.
        audit = AuditLog.query.filter_by(module='opening_balances').filter(
            AuditLog.action.in_(['update', 'request'])
        ).order_by(AuditLog.id.desc()).first()
        assert audit is not None

    def test_sole_accountant_request_auto_applies(self, client, db_session, db_with_data,
                                                   accountant_user):
        """With one accountant, request-change auto-approves and rebuilds the
        (posted) entry in place -- no pending state, no second reviewer needed."""
        cash = db_with_data['cash']
        revenue = db_with_data['revenue']
        branch = db_with_data['branch']
        _make_postable(db_session, cash, revenue)

        _login(client, accountant_user)
        _select_branch(client, branch.id)

        client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
            (cash.id, '1000.00', '0'), (revenue.id, '0', '1000.00'),
        ]))
        client.post('/opening-balances/post')

        AccountingPeriod.get_or_create_period(2026, 1).status = 'closed'
        db.session.commit()

        client.post('/opening-balances/request-change',
                    data=_post_line_form('2026-01-01', cash.id),
                    follow_redirects=True)

        req = OpeningBalanceChangeRequest.query.first()
        assert req is not None
        assert req.status == 'approved'
        assert req.reviewed_by == accountant_user.username
        assert req.reviewed_at is not None

        # The posted entry was rebuilt in place from the approved snapshot and
        # remains posted + balanced (not pushed back to draft, not left stale).
        entry = get_opening_entry(branch.id)
        assert entry.status == 'posted'
        assert entry.is_balanced
        assert float(entry.total_debit) == 100.00
        assert float(entry.total_credit) == 100.00

    def test_pending_request_blocks_a_second_request(self, client, db_session, db_with_data,
                                                      accountant_user, chief_accountant_user):
        """A second submitter cannot queue a second request while one is pending.
        Uses a chief_accountant peer alongside the accountant so the FIRST request
        does NOT auto-approve (count of accountant/CA == 2), proving the pending
        branch of request_change and its second-request guard."""
        cash = db_with_data['cash']
        revenue = db_with_data['revenue']
        branch = db_with_data['branch']
        _make_postable(db_session, cash, revenue)
        chief_accountant_user.set_branches([branch])
        db.session.commit()

        _login(client, accountant_user)
        _select_branch(client, branch.id)
        client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
            (cash.id, '1000.00', '0'), (revenue.id, '0', '1000.00'),
        ]))
        client.post('/opening-balances/post')

        AccountingPeriod.get_or_create_period(2026, 1).status = 'closed'
        db.session.commit()

        # Snapshot the posted entry BEFORE the first (pending) request-change POST.
        before = get_opening_entry(branch.id)
        pre_debit, pre_credit, pre_date = (
            before.total_debit, before.total_credit, before.entry_date)

        client.post('/opening-balances/request-change',
                    data=_post_line_form('2026-01-01', cash.id),
                    follow_redirects=True)
        assert OpeningBalanceChangeRequest.query.count() == 1
        first = OpeningBalanceChangeRequest.query.first()
        assert first.status == 'pending'  # two accountant/CA -> no auto-approve

        # The pending branch must NOT mutate the posted entry -- only an approved
        # request (auto or, in Task 5, an approver action) may rebuild it in place.
        after = get_opening_entry(branch.id)
        assert after.total_debit == pre_debit
        assert after.total_credit == pre_credit
        assert after.entry_date == pre_date

        # A second request while one is pending is refused, not queued.
        resp = client.post('/opening-balances/request-change',
                           data=_post_line_form('2026-01-01', cash.id),
                           follow_redirects=True)
        assert resp.status_code == 200
        assert OpeningBalanceChangeRequest.query.count() == 1
        assert b'already a pending' in resp.data

    def test_unbalanced_change_is_rejected_before_creating_request(
            self, client, db_session, db_with_data, accountant_user):
        """CRITICAL guard: a governed change with mismatched (or zero) debit/credit
        totals must be rejected up-front -- no OpeningBalanceChangeRequest created,
        and the already-posted opening entry's totals stay untouched. Without this,
        the sole-accountant auto-approve path would silently rebuild the posted
        entry into an unbalanced/empty state."""
        cash = db_with_data['cash']
        revenue = db_with_data['revenue']
        branch = db_with_data['branch']
        _make_postable(db_session, cash, revenue)

        _login(client, accountant_user)
        _select_branch(client, branch.id)

        client.post('/opening-balances/save', data=_save_payload('2026-01-01', [
            (cash.id, '1000.00', '0'), (revenue.id, '0', '1000.00'),
        ]))
        client.post('/opening-balances/post')

        AccountingPeriod.get_or_create_period(2026, 1).status = 'closed'
        db.session.commit()

        before = get_opening_entry(branch.id)
        pre_debit, pre_credit = before.total_debit, before.total_credit

        # One debit line, no offsetting credit -- unbalanced.
        resp = client.post('/opening-balances/request-change',
                           data={'cutover_date': '2026-01-01',
                                 'account_id': [str(cash.id)],
                                 'debit': ['500.00'], 'credit': ['0']},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert b'must be balanced' in resp.data
        assert OpeningBalanceChangeRequest.query.count() == 0

        after = get_opening_entry(branch.id)
        assert after.total_debit == pre_debit
        assert after.total_credit == pre_credit
