"""Action Items must list DRAFT Purchase Requests.

A draft PR is an unfinished document exactly like a draft AP/CDV/CRV/SI, so it
belongs in the Drafts panel and the sidebar badge. It was omitted from
_draft_sources() entirely, so a requisition saved as a draft appeared nowhere.

Purchase Requests differ from the four originally-wired sources in one way that
the tests below pin: those four are CORE modules, while `purchase_requests` is
OPTIONAL (default_enabled False) and per-user permissioned. So listing a PR
draft has to clear BOTH gates -- the instance package gate and the per-user book
permission -- or Action Items becomes a side channel that reports documents from
a module the instance disabled or the user cannot open.
"""
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest

pytestmark = [pytest.mark.integration]

# Distinctive on purpose: a generic number like '00001' also appears in unrelated
# markup on the page, so asserting it would pass without the feature existing.
PR_NUMBER = 'PRDRAFT-ZZ9'


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


def _make_draft_pr(db_session, branch, user, number=PR_NUMBER):
    pr = PurchaseRequest(
        pr_number=number, request_date=date.today(), branch_id=branch.id,
        status='draft', created_by_id=user.id, reason='Test requisition')
    db_session.add(pr)
    db_session.commit()
    return pr


class TestDraftPurchaseRequestInActionItems:

    def test_draft_pr_listed_for_admin(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        _make_draft_pr(db_session, main_branch, admin_user)
        _login(client, admin_user, main_branch)

        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert PR_NUMBER.encode() in resp.data
        assert b'Purchase Request' in resp.data

    def test_draft_pr_counted_in_badge(self, db_session, admin_user, main_branch):
        from app.dashboard.action_items_service import count_action_items
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')

        before = count_action_items(admin_user, main_branch.id)
        _make_draft_pr(db_session, main_branch, admin_user)
        after = count_action_items(admin_user, main_branch.id)

        # Exact, not ">=": an off-by-one or a double-count is a real defect here.
        assert after == before + 1

    def test_non_draft_pr_not_listed(self, client, db_session, admin_user, main_branch):
        """Control on the status filter. Without this, a source that ignored
        status='draft' and listed EVERY requisition would pass the test above."""
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        pr = _make_draft_pr(db_session, main_branch, admin_user)
        pr.status = 'approved'
        db_session.commit()
        _login(client, admin_user, main_branch)

        assert PR_NUMBER.encode() not in client.get('/action-items').data

    def test_draft_pr_hidden_when_module_disabled(self, client, db_session,
                                                  admin_user, main_branch):
        """The instance package gate. `purchase_requests` is optional, so an
        instance that never turned it on must not see requisitions surface in
        Action Items -- including for an admin, who bypasses the per-user gate
        but NOT the package gate."""
        _set_modules(db_session, '0', 'purchase_requests')
        _make_draft_pr(db_session, main_branch, admin_user)
        _login(client, admin_user, main_branch)

        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert PR_NUMBER.encode() not in resp.data

    def test_draft_pr_hidden_from_staff_without_module_permission(
            self, client, db_session, staff_user, main_branch):
        """The per-user gate. The module is enabled instance-wide and the draft
        is the staff user's OWN (so the created_by_id filter would pass it), but
        staff has no purchase_requests book permission -- which is why the fix
        must call can_access_module(), not merely module_enabled()."""
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        # Staff are branch-scoped: without an explicit assignment the before_request
        # branch guard redirects to the picker and the assertion below would pass
        # on a 302 that never rendered the page.
        staff_user.add_branch(main_branch)
        db_session.commit()
        assert staff_user.get_book_permissions().get('purchase_requests', False) is False
        _make_draft_pr(db_session, main_branch, staff_user)
        _login(client, staff_user, main_branch)

        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert PR_NUMBER.encode() not in resp.data

    def test_draft_pr_row_names_its_creator(self, client, db_session, admin_user, main_branch):
        """PurchaseRequest has no `created_by` relationship (only the column), so
        the row rendered 'by —' while every sibling named someone.

        The creator is deliberately NOT the logged-in user: the page header
        renders the CURRENT user's name, so asserting admin's own name here
        would pass whether or not the row displays anything at all.
        """
        from app.users.models import User
        _set_modules(db_session, '1', 'products', 'purchase_orders', 'purchase_requests')
        author = User(username='reqauthor', email='reqauthor@test.com',
                      full_name='Requisition Author ZZ9', role='staff', is_active=True)
        author.set_password('author123')
        db_session.add(author)
        db_session.commit()

        _make_draft_pr(db_session, main_branch, author)
        _login(client, admin_user, main_branch)

        resp = client.get('/action-items')
        assert PR_NUMBER.encode() in resp.data
        assert b'Requisition Author ZZ9' in resp.data

    def test_badge_count_excludes_pr_when_module_disabled(self, db_session,
                                                          admin_user, main_branch):
        """The badge and the list must agree. They are computed by two separate
        code paths (count_action_items vs gather_draft_items), so gating one and
        not the other yields a badge that counts an item the page never shows."""
        from app.dashboard.action_items_service import count_action_items
        _set_modules(db_session, '0', 'purchase_requests')

        before = count_action_items(admin_user, main_branch.id)
        _make_draft_pr(db_session, main_branch, admin_user)
        assert count_action_items(admin_user, main_branch.id) == before
