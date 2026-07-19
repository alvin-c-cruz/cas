"""
Playwright e2e smoke test for the sidebar accordion: expanding a collapsed
section, then clicking a link inside it, must succeed under Playwright's
normal (non-force) actionability click.

Written while investigating BUG-SIDEBAR-COLLAPSIBLE-CLICK-INTERCEPT, which
turned out NOT to be a product bug -- see that entry in project-bug-tracker
(WONTFIX, 2026-07-20): the accordion persists its open section in
localStorage across page loads and toggling an already-open section closes
it, which is what every failing repro attempt actually hit. Kept as a plain
smoke test for the expand-then-click flow on a section confirmed collapsed
via a fresh (localStorage-cleared) page load.

Run: pytest -m e2e -k sidebar_accordion
"""
import pytest

pytestmark = [pytest.mark.e2e]


def test_expand_admin_then_click_branch_management_no_force(logged_in_page):
    page = logged_in_page
    assert '/dashboard' in page.url
    page.evaluate("() => localStorage.removeItem('sidebar:expandedSection')")
    page.reload()
    page.wait_for_load_state('networkidle')

    admin_label = page.locator('[data-section="admin"]')
    assert 'collapsed' in (admin_label.get_attribute('class') or '')

    admin_label.click()
    page.click('text=Branch Management')
    page.wait_for_load_state('networkidle')

    assert '/branches' in page.url
