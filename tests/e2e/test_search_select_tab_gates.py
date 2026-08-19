"""
Playwright e2e tests for TAB-TO-SELECT on the shared search-select picker
(app/static/search-select.js::initSearchSelect) -- the DO-NOT-COMMIT half.

Every case here is one where the dropdown is involved but Tab must select
NOTHING. Silently writing a value the user never chose is worse than having no
Tab shortcut at all: it is a wrong vendor on a real voucher, and the user has
no reason to look for it.

The scenarios were chosen by MEASURING the live DOM at the moment Tab is
pressed, not by reasoning about it -- the obvious ones prove nothing, and
picking them produced tests that stayed green with the guard deleted:

  * "just opened"     -- Choices highlights the PLACEHOLDER row (data-value
                         ''), so the empty value already blocks the commit and
                         every guard looks like it works.
  * "typed, Escape"   -- Escape CLEARS the search input, so a different guard
                         catches it than the one the test claims to exercise.
  * "cleared query"   -- which row stays highlighted varies between runs, so
                         which guard blocks it varies too.

Each docstring below says whether the test pins a GUARD (a line of our JS,
mutation-proven) or a BEHAVIOUR (an outcome enforced by something structural).
Do not upgrade a BEHAVIOUR label to GUARD without re-running the mutation.

Split from test_search_select_tab.py: the e2e server is module-scoped and
degrades over a long run (see conftest.py), and 11 logins against one server
times out the last test's post-login wait.
"""
import pytest

from tests.e2e._picker_helpers import (
    DROPDOWN, DROPDOWN_IS_OPEN, HIGHLIGHTED, HIGHLIGHTED_VALUE,
    assert_nothing_selected, assert_real_row_highlighted, open_vendor_picker,
)

pytestmark = [pytest.mark.e2e, pytest.mark.accounts_payable]


def test_tab_without_typing_or_arrowing_does_not_select(logged_in_page, e2e_server):
    """Open a picker, touch nothing, tab straight out -> no vendor."""
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert_nothing_selected(page, scope, 'untouched picker')


def test_tab_on_a_query_matching_nothing_does_not_select(logged_in_page, e2e_server):
    """No match means no highlighted row means nothing to commit."""
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.keyboard.type('zzzznotavendor')
    page.wait_for_selector(DROPDOWN + ' .search-select-noresults')
    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert_nothing_selected(page, scope, 'query matching nothing')


def test_tab_after_escape_does_not_select(logged_in_page, e2e_server):
    """BEHAVIOUR: Escape then Tab commits nothing.

    Worth pinning even though no line of our JS enforces it. What enforces it
    is structural: the search input lives inside the dropdown, so closing the
    dropdown moves focus to div.choices and the keydown handler never fires
    again (measured -- an explicit is-the-dropdown-open check was tried here
    and proved unfalsifiable, so it was removed rather than left as decoration).
    If a future Choices upgrade keeps that input focusable while closed, the
    structure stops protecting us and this test is what notices.
    """
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.keyboard.press('ArrowDown')
    page.keyboard.press('ArrowDown')
    page.wait_for_selector(HIGHLIGHTED)
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)
    assert not page.evaluate(DROPDOWN_IS_OPEN), 'Escape did not close the dropdown'
    assert page.evaluate(HIGHLIGHTED_VALUE), (
        'Escape cleared the highlight too, so there was nothing Tab could have '
        'committed either way -- this test would pass vacuously'
    )

    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert_nothing_selected(page, scope, 'dropdown already closed')


def test_tab_after_clearing_the_query_does_not_select(logged_in_page, e2e_server):
    """BEHAVIOUR: deleting the query cancels the choice.

    The dropdown stays open with a row still highlighted after the query is
    backspaced away, so there IS something Tab could commit. Which row that is
    varies between runs (Choices re-renders the restored full list
    asynchronously -- observed as both the first vendor and the pinned
    add-action), so this test pins the OUTCOME, not the mechanism: whatever is
    left highlighted, the user deleted what they typed and must get nothing.
    """
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.keyboard.type('V003')
    page.wait_for_selector(HIGHLIGHTED)
    for _ in range(8):
        page.keyboard.press('Backspace')
    page.wait_for_timeout(300)
    assert page.evaluate(HIGHLIGHTED_VALUE), \
        'no row is highlighted after clearing -- this test proves nothing'

    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert_nothing_selected(page, scope, 'query deleted')


def test_arrowing_then_reopening_does_not_carry_the_choice_over(logged_in_page, e2e_server):
    """GUARD: the expressed-choice flag resets on every open.

    Arrow (expressed), Escape, reopen: the highlight survives in the DOM, so an
    un-reset flag would commit that stale row on an untouched second visit.
    """
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.keyboard.press('ArrowDown')
    page.keyboard.press('ArrowDown')
    page.wait_for_selector(HIGHLIGHTED)
    page.keyboard.press('Escape')
    page.wait_for_timeout(200)

    scope.locator('.choices__inner').click()          # reopen, touch nothing
    page.wait_for_selector(DROPDOWN + ' .choices__item')
    page.wait_for_timeout(300)
    assert_real_row_highlighted(page, 'reopened picker')

    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert_nothing_selected(page, scope, 'stale highlight from an earlier open')


def test_tab_on_the_add_action_does_not_select_or_open_the_modal(logged_in_page, e2e_server):
    """GUARD: the pinned add-action is not a choice.

    It opens a quick-add modal; tabbing past a field must never do that.
    """
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.keyboard.press('ArrowDown')          # lands on the pinned add-action
    highlighted = page.locator(HIGHLIGHTED).first.inner_text().strip()
    assert 'Add Vendor' in highlighted, f'expected the add-action first, got {highlighted!r}'

    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert_nothing_selected(page, scope, 'add-action highlighted')
    assert not page.locator('#vendorQuickAddOverlay').is_visible(), \
        'Tab opened the vendor quick-add modal'


def test_shift_tab_does_not_select(logged_in_page, e2e_server):
    """Only forward Tab commits -- tabbing BACKWARDS out is the escape hatch."""
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.keyboard.type('V002')
    page.wait_for_selector(HIGHLIGHTED)
    page.keyboard.press('Shift+Tab')
    page.wait_for_timeout(300)

    assert_nothing_selected(page, scope, 'Shift+Tab')
