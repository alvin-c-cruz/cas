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

    def test_the_memo_is_styled_as_a_return_not_a_rejection(self, client, accountant_user,
                                                            main_branch, db_session):
        """The three memos a requisition can carry -- Note, Rejected, Returned to draft --
        used to render as identical <p> lines, so the trail could only be read by parsing
        each label. Colour now carries the kind (owner, 2026-09-06).

        Asserted on the APPLIED class attribute, not the bare class name: `.record-memo`
        also appears in the inline stylesheet served in this same response, so a substring
        probe for the name alone could never fail.
        """
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status='rejected')
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'class="record-memo record-memo--returned"' in body
        # ...and it is NOT wearing the rejection's colour, which is the whole point of
        # giving them different ones.
        marker = body.split('Returned to draft:')[0].rsplit('<p', 1)[1]
        assert 'record-memo--rejected' not in marker

    def test_a_returned_requisition_still_shows_the_rejection_it_reverses(
            self, client, accountant_user, main_branch, db_session):
        """Both memos read in order, in different colours. A return does not un-happen the
        decision it reverses, and red must keep meaning `rejected` alone or the two
        compete on a record carrying both."""
        _login(client, accountant_user, main_branch)
        pr = _make_pr(db_session, main_branch, status='rejected')
        pr.reject_reason = 'Wrong cost centre.'
        db_session.commit()
        client.post(f'/purchase-requests/{pr.id}/return-to-draft',
                    data={'return_reason': MEMO})
        body = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'class="record-memo record-memo--rejected"' in body
        assert 'class="record-memo record-memo--returned"' in body


class TestResubmittingClearsThePreviousCycle:
    """Owner, 2026-09-06: "once re-submitted, the notices should disappear."

    A rejection and a return-to-draft memo describe ONE review cycle. Submitting starts
    the next one, so carrying them forward made a freshly submitted requisition still read
    "Rejected: ..." on its own page -- describing a decision that had since been reversed
    and acted on.

    Cleared rather than hidden. Hiding cannot stay correct: a requisition rejected,
    returned, re-submitted and rejected AGAIN would pair its new rejection with the
    previous cycle's return memo, and no display rule keyed on status can tell those
    apart. The audit log keeps the history either way -- reject() and return_to_draft()
    each write the full memo into it.
    """

    def _returned_pr(self, client, db_session, main_branch, user):
        """A requisition that was rejected, then returned to draft -- carrying BOTH."""
        _login(client, user, main_branch)
        pr = _make_pr(db_session, main_branch, status='rejected')
        pr.reject_reason = 'Wrong cost centre.'
        pr.rejected_by_id = user.id
        db_session.commit()
        client.post('/purchase-requests/%s/return-to-draft' % pr.id,
                    data={'return_reason': MEMO})
        db_session.refresh(pr)
        assert pr.status == 'draft'
        assert pr.return_reason and pr.reject_reason      # both really are set
        return pr

    def test_both_memos_are_cleared_on_submit(self, client, accountant_user,
                                              main_branch, db_session):
        pr = self._returned_pr(client, db_session, main_branch, accountant_user)
        client.post('/purchase-requests/%s/submit' % pr.id)
        db_session.refresh(pr)
        assert pr.status == 'submitted'
        assert pr.reject_reason is None
        assert pr.return_reason is None

    def test_the_provenance_goes_with_them(self, client, accountant_user,
                                           main_branch, db_session):
        """A returned_at with no return_reason is a worse record than neither -- it says
        something happened and refuses to say what."""
        pr = self._returned_pr(client, db_session, main_branch, accountant_user)
        client.post('/purchase-requests/%s/submit' % pr.id)
        db_session.refresh(pr)
        for field in ('rejected_by_id', 'rejected_at', 'returned_by_id', 'returned_at'):
            assert getattr(pr, field) is None, field

    def test_neither_notice_renders_after_resubmission(self, client, accountant_user,
                                                       main_branch, db_session):
        """THE reported symptom, at the page level."""
        pr = self._returned_pr(client, db_session, main_branch, accountant_user)
        client.post('/purchase-requests/%s/submit' % pr.id)
        body = client.get('/purchase-requests/%s' % pr.id).data.decode()
        assert 'Returned to draft:' not in body
        assert 'Rejected:' not in body
        assert MEMO not in body

    def test_the_requesters_own_note_survives(self, client, accountant_user,
                                              main_branch, db_session):
        """CONTROL, and a real distinction: `reason` is the requester's own note about
        WHAT is being asked for. It belongs to the document, not to a review cycle, so
        clearing the review memos must not take it too."""
        pr = self._returned_pr(client, db_session, main_branch, accountant_user)
        pr.reason = 'For the conveyor line refit.'
        db_session.commit()
        client.post('/purchase-requests/%s/submit' % pr.id)
        db_session.refresh(pr)
        assert pr.reason == 'For the conveyor line refit.'
        body = client.get('/purchase-requests/%s' % pr.id).data.decode()
        assert 'For the conveyor line refit.' in body

    def test_the_history_survives_in_the_audit_log(self, client, accountant_user,
                                                   main_branch, db_session):
        """What makes clearing safe rather than destructive. If this ever stops holding,
        the clear above becomes the only copy being deleted."""
        from app.audit.models import AuditLog
        pr = self._returned_pr(client, db_session, main_branch, accountant_user)
        client.post('/purchase-requests/%s/submit' % pr.id)
        notes = ' '.join(
            (e.notes or '') for e in
            AuditLog.query.filter_by(module='purchase_requests', record_id=pr.id).all())
        assert MEMO in notes
        assert 'Returned to draft from rejected' in notes

    def test_a_second_rejection_does_not_drag_the_old_return_memo_along(
            self, client, admin_user, accountant_user, main_branch, db_session):
        """The case a status-keyed display rule could not get right, which is why this is
        a clear and not a filter."""
        pr = self._returned_pr(client, db_session, main_branch, accountant_user)
        client.post('/purchase-requests/%s/submit' % pr.id)
        _login(client, admin_user, main_branch)
        client.post('/purchase-requests/%s/reject' % pr.id,
                    data={'reject_reason': 'Budget exhausted for the quarter.'})
        db_session.refresh(pr)
        assert pr.reject_reason == 'Budget exhausted for the quarter.'
        assert pr.return_reason is None
        body = client.get('/purchase-requests/%s' % pr.id).data.decode()
        assert 'Budget exhausted for the quarter.' in body
        assert MEMO not in body
