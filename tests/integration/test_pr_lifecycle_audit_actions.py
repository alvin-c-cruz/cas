"""Each PR lifecycle transition gets its own audit ACTION, not generic 'update'.

submit / reject / cancel all logged action='update' with the real event buried in
`notes`, while amend / approve / convert already had proper actions. In the audit
log UI a submission was therefore indistinguishable from an ordinary edit without
opening View Details, and the Actions filter -- which is built from the DISTINCT
actions present -- offered no way to select them.

All three are fixed together: they are the same copy-pasted defect, and leaving
two of them behind would keep the filter incomplete.
"""
from datetime import date

import pytest

from app.audit.models import AuditLog
from app.purchase_requests.models import PurchaseRequest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]

REASON = 'Superseded by a revised requisition'   # >= 10 chars, both routes require it


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()


def _pr(db_session, branch, user, status='draft', number='LIFECYCLE-1'):
    pr = PurchaseRequest(pr_number=number, request_date=date.today(),
                         branch_id=branch.id, status=status, created_by_id=user.id,
                         submitted_by_id=user.id if status != 'draft' else None)
    db_session.add(pr)
    db_session.commit()
    return pr


def _actions_for(pr):
    return [a.action for a in AuditLog.query.filter_by(
        module='purchase_requests', record_id=pr.id).all()]


class TestLifecycleAuditActions:

    def test_submit_logs_submit(self, client, db_session, admin_user, main_branch):
        _enable(db_session)
        pr = _pr(db_session, main_branch, admin_user)
        _login(client, admin_user, main_branch)

        client.post(f'/purchase-requests/{pr.id}/submit')

        assert 'submit' in _actions_for(pr)
        # Not merely "a submit row exists": the generic row must be GONE, or the
        # log still carries an indistinguishable 'update' beside it.
        assert 'update' not in _actions_for(pr)

    def test_reject_logs_reject(self, client, db_session, admin_user, main_branch):
        _enable(db_session)
        pr = _pr(db_session, main_branch, admin_user, status='submitted')
        _login(client, admin_user, main_branch)

        client.post(f'/purchase-requests/{pr.id}/reject',
                    data={'reject_reason': REASON})

        assert 'reject' in _actions_for(pr)
        assert 'update' not in _actions_for(pr)

    def test_cancel_logs_cancel(self, client, db_session, admin_user, main_branch):
        _enable(db_session)
        pr = _pr(db_session, main_branch, admin_user)
        _login(client, admin_user, main_branch)

        client.post(f'/purchase-requests/{pr.id}/cancel',
                    data={'cancel_reason': REASON})

        assert 'cancel' in _actions_for(pr)
        assert 'update' not in _actions_for(pr)

    def test_reason_is_still_recorded_in_notes(self, client, db_session, admin_user,
                                               main_branch):
        """The action must not replace the detail -- a rejection is only auditable
        if the reason survives alongside the new action name."""
        _enable(db_session)
        pr = _pr(db_session, main_branch, admin_user, status='submitted')
        _login(client, admin_user, main_branch)

        client.post(f'/purchase-requests/{pr.id}/reject',
                    data={'reject_reason': REASON})

        entry = AuditLog.query.filter_by(module='purchase_requests',
                                         record_id=pr.id, action='reject').first()
        assert entry is not None
        assert REASON in (entry.notes or '')

    def test_editing_a_draft_still_logs_update(self, client, db_session, admin_user,
                                               main_branch):
        """Control on the path this change did NOT mean to touch. An ordinary edit
        is genuinely an update and must keep that action, or the fix has simply
        renamed everything."""
        _enable(db_session)
        pr = _pr(db_session, main_branch, admin_user)
        _login(client, admin_user, main_branch)

        resp = client.post(f'/purchase-requests/{pr.id}/edit', data={
            'pr_number': pr.pr_number,
            'request_date': pr.request_date.strftime('%Y-%m-%d'),
            'reason': 'Edited reason text',
            # RowVersionFormMixin: omitting this makes submitted_version() read 0,
            # claim_version() refuse, and the route fall through to a conflict --
            # so the test would "pass" for the wrong reason if it asserted a
            # redirect rather than the audit row.
            'row_version': pr.row_version,
            'line_items': '[{"description": "Bolt", "quantity": "1"}]',
        }, follow_redirects=True)

        assert b'updated' in resp.data, resp.get_data(as_text=True)[:400]
        assert 'update' in _actions_for(pr)
