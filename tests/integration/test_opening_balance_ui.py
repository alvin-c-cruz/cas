"""Task 6: OB pending-approvals branch-name rendering, action-items count, and the
form-switch to the governed request-change path once the period is closed.

Reuses the login/branch-select/save/postable-leaf helpers from
tests/integration/test_opening_balances.py and the pending-request setup helper
from tests/integration/test_opening_balance_approval_routes.py rather than
inventing new fixtures.
"""
import pytest

from app import db
from app.periods.models import AccountingPeriod
from app.opening_balances.approval_models import OpeningBalanceChangeRequest
from app.dashboard.action_items_service import count_action_items

from tests.integration.test_opening_balances import (
    _login, _select_branch, _save_payload, _make_postable,
)
from tests.integration.test_opening_balance_approval_routes import (
    _setup_pending_request,
)

pytestmark = [pytest.mark.integration]


class TestOpeningBalanceActionItemsCount:

    def test_count_action_items_includes_pending_ob_request(
            self, db_session, accountant_user, main_branch):
        before = count_action_items(accountant_user, main_branch.id)

        req = OpeningBalanceChangeRequest(
            branch_id=main_branch.id, requested_by='someone_else', status='pending')
        req.set_change_data({'cutover_date': '2026-01-01', 'lines': []})
        db_session.add(req)
        db_session.commit()

        after = count_action_items(accountant_user, main_branch.id)
        assert after == before + 1


class TestOpeningBalancePendingApprovalsBranchName:

    def test_pending_approvals_renders_branch_name_not_raw_id(
            self, client, db_session, db_with_data, accountant_user,
            chief_accountant_user):
        branch, cash, revenue, req = _setup_pending_request(
            client, db_session, db_with_data, accountant_user, chief_accountant_user)

        resp = client.get('/opening-balances/pending-approvals')
        assert resp.status_code == 200
        # The branch NAME must render...
        assert branch.name.encode() in resp.data
        # ...not the raw id alone in the branch cell.
        assert f'<td>{branch.id}</td>'.encode() not in resp.data
        # The request row itself is present (View/detail toggle keyed by id).
        assert f'viewDetails({req.id})'.encode() in resp.data


class TestOpeningBalanceIndexFormSwitch:

    def test_index_open_period_posts_to_save(
            self, client, db_session, db_with_data, accountant_user):
        cash = db_with_data['cash']
        revenue = db_with_data['revenue']
        branch = db_with_data['branch']
        _make_postable(db_session, cash, revenue)
        _login(client, accountant_user)
        _select_branch(client, branch.id)

        resp = client.get('/opening-balances')
        assert resp.status_code == 200
        assert b'/opening-balances/save' in resp.data
        assert b'/opening-balances/request-change' not in resp.data

    def test_index_closed_period_posts_to_request_change(
            self, client, db_session, db_with_data, accountant_user):
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

        resp = client.get('/opening-balances')
        assert resp.status_code == 200
        assert b'/opening-balances/request-change' in resp.data
        assert b'Submit Change Request' in resp.data
