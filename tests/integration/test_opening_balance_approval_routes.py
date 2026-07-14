"""Task 5: approve/reject routes for OpeningBalanceChangeRequest.

Reuses the login/branch-select/save/postable-leaf helpers already established in
tests/integration/test_opening_balances.py (and Task 4's gating tests) rather than
inventing a new pattern. Uses TWO accountants (accountant_user + chief_accountant_user)
so a submitted request goes 'pending' (not auto-approved) and can be approved by a peer.
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


def _switch_user(client, username, password):
    """Log out the current session, then log in as a different user via a REAL
    form POST -- required when switching identity mid-test. Flask-Login's strong
    session protection invalidates a bare session_transaction()-set _user_id when
    the session was previously authenticated as someone else (see
    test_change_request_workflow.py's 'must log out before switching users'
    convention, which likewise uses a real POST /login, not session_transaction)."""
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def _setup_pending_request(client, db_session, db_with_data, accountant_user,
                            chief_accountant_user):
    """Post+balance an opening entry, close its period, have the accountant submit
    a governed change while a chief_accountant peer exists (-> pending, not
    auto-approved). Returns (branch, cash, revenue, req)."""
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

    client.post('/opening-balances/request-change',
                data=_post_line_form('2026-01-01', cash.id),
                follow_redirects=True)
    req = OpeningBalanceChangeRequest.query.first()
    assert req is not None
    assert req.status == 'pending'
    return branch, cash, revenue, req


@pytest.mark.integration
class TestOpeningBalanceApprovalRoutes:

    def test_peer_approves_pending_request(self, client, db_session, db_with_data,
                                            accountant_user, chief_accountant_user):
        branch, cash, revenue, req = _setup_pending_request(
            client, db_session, db_with_data, accountant_user, chief_accountant_user)

        _switch_user(client, chief_accountant_user.username, 'chief123')
        _select_branch(client, branch.id)
        resp = client.post(f'/opening-balances/approve/{req.id}', follow_redirects=True)
        assert resp.status_code == 200

        req = db.session.get(OpeningBalanceChangeRequest, req.id)
        assert req.status == 'approved'
        assert req.reviewed_by == chief_accountant_user.username
        assert req.reviewed_at is not None

        entry = get_opening_entry(branch.id)
        assert entry.status == 'posted'
        assert entry.is_balanced
        assert float(entry.total_debit) == 100.00
        assert float(entry.total_credit) == 100.00
        assert entry.entry_date == date(2026, 1, 1)

        audit = AuditLog.query.filter_by(
            module='opening_balances', action='update').order_by(
            AuditLog.id.desc()).first()
        assert audit is not None

    def test_requester_cannot_approve_own_request(self, client, db_session, db_with_data,
                                                    accountant_user, chief_accountant_user):
        branch, cash, revenue, req = _setup_pending_request(
            client, db_session, db_with_data, accountant_user, chief_accountant_user)

        before = get_opening_entry(branch.id)
        pre_debit, pre_credit = before.total_debit, before.total_credit

        # accountant_user (the requester) is still logged in from setup.
        resp = client.post(f'/opening-balances/approve/{req.id}', follow_redirects=True)
        assert resp.status_code == 200

        req = db.session.get(OpeningBalanceChangeRequest, req.id)
        assert req.status == 'pending'

        after = get_opening_entry(branch.id)
        assert after.total_debit == pre_debit
        assert after.total_credit == pre_credit

    def test_reject_records_reason_and_audits(self, client, db_session, db_with_data,
                                               accountant_user, chief_accountant_user):
        branch, cash, revenue, req = _setup_pending_request(
            client, db_session, db_with_data, accountant_user, chief_accountant_user)

        _switch_user(client, chief_accountant_user.username, 'chief123')
        _select_branch(client, branch.id)
        resp = client.post(f'/opening-balances/reject/{req.id}',
                           data={'rejection_reason': 'Numbers do not tie to source docs.'},
                           follow_redirects=True)
        assert resp.status_code == 200

        req = db.session.get(OpeningBalanceChangeRequest, req.id)
        assert req.status == 'rejected'
        assert req.rejection_reason == 'Numbers do not tie to source docs.'
        assert req.reviewed_by == chief_accountant_user.username
        assert req.reviewed_at is not None

        audit = AuditLog.query.filter_by(
            module='opening_balances', action='reject').order_by(
            AuditLog.id.desc()).first()
        assert audit is not None

    def test_approve_missing_request_flashes_and_noops(self, client, db_session,
                                                         db_with_data, accountant_user,
                                                         chief_accountant_user):
        branch = db_with_data['branch']
        chief_accountant_user.set_branches([branch])
        db.session.commit()
        _switch_user(client, chief_accountant_user.username, 'chief123')
        _select_branch(client, branch.id)

        resp = client.post('/opening-balances/approve/999999', follow_redirects=True)
        assert resp.status_code == 404

    def test_approve_already_processed_request_flashes_and_noops(
            self, client, db_session, db_with_data, accountant_user,
            chief_accountant_user):
        branch, cash, revenue, req = _setup_pending_request(
            client, db_session, db_with_data, accountant_user, chief_accountant_user)

        _switch_user(client, chief_accountant_user.username, 'chief123')
        _select_branch(client, branch.id)
        client.post(f'/opening-balances/approve/{req.id}', follow_redirects=True)
        req = db.session.get(OpeningBalanceChangeRequest, req.id)
        assert req.status == 'approved'

        entry_before = get_opening_entry(branch.id)
        pre_debit, pre_date = entry_before.total_debit, entry_before.entry_date

        # Second approve attempt on the now-approved request: no-op with a flash.
        resp = client.post(f'/opening-balances/approve/{req.id}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'already been processed' in resp.data

        entry_after = get_opening_entry(branch.id)
        assert entry_after.total_debit == pre_debit
        assert entry_after.entry_date == pre_date

    def test_pending_approvals_page_lists_pending_requests(
            self, client, db_session, db_with_data, accountant_user,
            chief_accountant_user):
        branch, cash, revenue, req = _setup_pending_request(
            client, db_session, db_with_data, accountant_user, chief_accountant_user)

        _switch_user(client, chief_accountant_user.username, 'chief123')
        _select_branch(client, branch.id)
        resp = client.get('/opening-balances/pending-approvals')
        assert resp.status_code == 200
        assert accountant_user.username.encode() in resp.data
