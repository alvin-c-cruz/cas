"""A requisition can be sent BACK to draft, with a memo saying why.

Two source states reach it (owner request 2026-09-06):

  submitted -> draft   the approver's third choice beside Approve and Reject:
                       send it back to be fixed rather than refuse it outright.
  rejected  -> draft   recovery from a decision already made. Before this,
                       `rejected` was terminal -- not editable, not
                       resubmittable, not even cancellable -- so a requisition
                       refused for a fixable reason (e.g. its number must follow
                       the client's old manual sequence) had to be abandoned and
                       rekeyed, losing its lines and its audit thread.

The memo is the point of the feature, so it is required and it is asserted
everywhere it should survive: on the record, in the audit note, and on the page.
"""
from datetime import date
from decimal import Decimal
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _make_pr(db_session, branch, status='submitted', number='PR-RET-1'):
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 9, 6), status=status,
                         reason='Site needs cement')
    pr.line_items.append(PurchaseRequestItem(line_number=1, description='Cement',
                                             quantity=Decimal('10'), uom_text='bag'))
    db_session.add(pr); db_session.commit()
    return pr


MEMO = 'PR number should follow the old manual PR sequence.'


class TestItReturnsToDraft:

    @pytest.mark.parametrize('start', ['submitted', 'rejected'])
    def test_both_source_states_go_back_to_draft(self, client, accountant_user,
                                                 main_branch, db_session, start):
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status=start, number=f'PR-RET-{start}')
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        db_session.refresh(pr)
        assert pr.status == 'draft'
        assert pr.return_reason == MEMO
        assert pr.returned_by_id == accountant_user.id
        assert pr.returned_at is not None

    def test_the_returned_pr_is_editable_again(self, client, accountant_user,
                                               main_branch, db_session):
        """The whole point: `rejected` was a dead end, and edit is draft-only."""
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status='rejected')
        assert client.get(f'/purchase-requests/{pr.id}/edit').status_code == 302
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        assert client.get(f'/purchase-requests/{pr.id}/edit').status_code == 200

    def test_the_rejection_is_not_erased(self, client, accountant_user, main_branch,
                                         db_session):
        """Returning reverses the decision; it does not un-happen it."""
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status='submitted')
        client.post(f'/purchase-requests/{pr.id}/reject',
                    data={'reject_reason': 'Wrong number series entirely'})
        db_session.refresh(pr)
        assert pr.status == 'rejected'
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        db_session.refresh(pr)
        assert pr.status == 'draft'
        assert pr.reject_reason == 'Wrong number series entirely'   # intact
        assert pr.rejected_by_id is not None
        assert pr.return_reason == MEMO


class TestTheMemoIsRequired:

    @pytest.mark.parametrize('bad', ['', '   ', 'too short'])
    def test_a_missing_or_short_memo_is_refused(self, client, accountant_user,
                                                main_branch, db_session, bad):
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status='rejected')
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': bad})
        db_session.refresh(pr)
        assert pr.status == 'rejected'          # unchanged
        assert pr.return_reason is None


class TestTheStateGuard:

    @pytest.mark.parametrize('start', ['draft', 'approved', 'converted', 'cancelled'])
    def test_other_states_are_refused(self, client, accountant_user, main_branch,
                                      db_session, start):
        """Only submitted and rejected are returnable. `approved` is excluded on
        purpose -- convert it or cancel it; converted/cancelled are terminal and
        a PO may already point at the first."""
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status=start, number=f'PR-RET-{start}')
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        db_session.refresh(pr)
        assert pr.status == start
        assert pr.return_reason is None


class TestPermission:

    def test_staff_cannot_return_to_draft(self, client, staff_user, main_branch,
                                          db_session):
        _login(client, staff_user, main_branch)
        pr = _make_pr(db_session, main_branch, status='rejected')
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        db_session.refresh(pr)
        assert pr.status == 'rejected'


class TestItIsAudited:

    def test_the_audit_row_records_the_memo_and_the_source_state(
            self, client, accountant_user, main_branch, db_session):
        from app.audit.models import AuditLog
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status='rejected')
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        row = AuditLog.query.filter_by(module='purchase_requests',
                                       action='return_to_draft',
                                       record_id=pr.id).first()
        assert row is not None
        assert MEMO in row.notes
        assert 'from rejected' in row.notes


class TestTheButtonIsOffered:

    @pytest.mark.parametrize('start', ['submitted', 'rejected'])
    def test_the_button_shows_on_returnable_states(self, client, accountant_user,
                                                   main_branch, db_session, start):
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status=start, number=f'PR-BTN-{start}')
        body = client.get(f'/purchase-requests/{pr.id}').data
        assert b'Return to Draft' in body
        assert bytes(f'/purchase-requests/{pr.id}/return-to-draft', 'utf-8') in body

    @pytest.mark.parametrize('start', ['draft', 'approved'])
    def test_the_button_is_withheld_elsewhere(self, client, accountant_user,
                                              main_branch, db_session, start):
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status=start, number=f'PR-NOBTN-{start}')
        body = client.get(f'/purchase-requests/{pr.id}').data
        assert b'Return to Draft' not in body

    def test_the_memo_is_shown_on_the_page(self, client, accountant_user,
                                           main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status='rejected')
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'Returned to draft:' in body
        assert MEMO in body
