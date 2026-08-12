"""A Purchase Request awaiting approval must surface in Action Items.

Submitting removed a PR from the Drafts panel (which filters status='draft') and
NOTHING picked it up: gather_approval_items() only ever covered master-data change
requests -- accounts, VAT, WHT, opening balances, permissions, approved emails --
so Action Items had no notion of DOCUMENT approvals at all. The one state that
actually needs somebody's attention was the one state the page could not see.

Audience is the approver, not the module user: submitting is open to staff, but
approving is accountant/full-access only (purchase_requests.views._approve_gate).
An item nobody can action is noise.
"""
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest

pytestmark = [pytest.mark.integration]

PR_NUMBER = 'PRAPPROVE-Z9'


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _set_modules(db_session, value, *keys):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', value)
    db_session.commit()
    clear_module_config_cache()


def _make_pr(db_session, branch, user, status='submitted', number=PR_NUMBER):
    pr = PurchaseRequest(pr_number=number, request_date=date.today(),
                         branch_id=branch.id, status=status,
                         created_by_id=user.id,
                         submitted_by_id=user.id if status != 'draft' else None)
    db_session.add(pr)
    db_session.commit()
    return pr


class TestSubmittedPrIsListedForApproval:

    def test_submitted_pr_appears(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        _make_pr(db_session, main_branch, admin_user)
        _login(client, admin_user, main_branch)

        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert PR_NUMBER.encode() in resp.data

    def test_review_link_points_at_the_requisition(self, client, db_session,
                                                   admin_user, main_branch):
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        pr = _make_pr(db_session, main_branch, admin_user)
        _login(client, admin_user, main_branch)

        assert f'/purchase-requests/{pr.id}'.encode() in client.get('/action-items').data

    def test_badge_counts_it(self, db_session, admin_user, main_branch):
        from app.dashboard.action_items_service import count_action_items
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')

        before = count_action_items(admin_user, main_branch.id)
        _make_pr(db_session, main_branch, admin_user)
        assert count_action_items(admin_user, main_branch.id) == before + 1

    def test_draft_is_not_double_counted(self, client, db_session, admin_user,
                                         main_branch):
        """A draft belongs to Drafts only. If the approval source forgot its
        status filter the same requisition would appear in BOTH panels."""
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        _make_pr(db_session, main_branch, admin_user, status='draft')
        _login(client, admin_user, main_branch)

        assert client.get('/action-items').data.count(PR_NUMBER.encode()) == 1

    def test_approved_pr_is_not_listed(self, client, db_session, admin_user,
                                       main_branch):
        """Control on the status filter -- an approved requisition needs nobody."""
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        _make_pr(db_session, main_branch, admin_user, status='approved')
        _login(client, admin_user, main_branch)

        assert PR_NUMBER.encode() not in client.get('/action-items').data


class TestApprovalAudienceIsTheApprover:

    def test_staff_who_may_submit_but_not_approve_does_not_see_it(
            self, db_session, admin_user, staff_user, main_branch):
        """Asserted against the SERVICE, not the rendered page.

        action_items.html wraps the whole "For Approval" panel in its own
        `has_full_access or accountant` check, so a page-level assertion passes
        even with the service gate deleted -- it proves the template guard and
        nothing else. Verified: removing _can_approve_documents' rule left a
        page-level version of this test green.

        Staff is granted the MODULE on purpose, so the approver rule is the only
        thing left that can exclude them.
        """
        from app.dashboard.action_items_service import gather_document_approval_items
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        staff_user.add_branch(main_branch)
        perms = staff_user.get_book_permissions()
        perms['purchase_requests'] = True
        staff_user.set_book_permissions(perms)
        db_session.commit()
        _make_pr(db_session, main_branch, admin_user)

        assert gather_document_approval_items(staff_user, main_branch.id) == []

    def test_staff_badge_does_not_count_it(self, db_session, admin_user,
                                           staff_user, main_branch):
        """The badge is computed by the service alone -- no template guard sits in
        front of it -- so a leaked approval would show staff a count they can
        never clear."""
        from app.dashboard.action_items_service import count_action_items
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        staff_user.add_branch(main_branch)
        perms = staff_user.get_book_permissions()
        perms['purchase_requests'] = True
        staff_user.set_book_permissions(perms)
        db_session.commit()

        before = count_action_items(staff_user, main_branch.id)
        _make_pr(db_session, main_branch, admin_user)
        assert count_action_items(staff_user, main_branch.id) == before

    def test_hidden_when_module_disabled(self, client, db_session, admin_user,
                                         main_branch):
        _set_modules(db_session, '0', 'purchase_requests')
        _make_pr(db_session, main_branch, admin_user)
        _login(client, admin_user, main_branch)

        assert PR_NUMBER.encode() not in client.get('/action-items').data
