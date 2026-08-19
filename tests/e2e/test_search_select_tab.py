"""
Playwright e2e regression tests for TAB-TO-SELECT on the shared search-select
picker (app/static/search-select.js::initSearchSelect).

Requested behaviour: while the dropdown is OPEN, pressing Tab commits the
highlighted choice and moves focus on to the next field -- the data-entry flow
is "type V002, Tab, keep typing" with no mouse and no Enter.

The gate is deliberately narrower than "dropdown is open" alone: Tab only
commits when the user has actually EXPRESSED a choice, i.e. typed a query or
moved the highlight with the arrow keys. Merely clicking a picker open and
tabbing straight back out must NOT silently write the first alphabetical row
into the field -- that is a wrong value the user never chose, and it is worse
than no autocomplete at all. The two `does_not_select` tests below are the
controls that pin that distinction.

Vendors V001-V004 are seeded by tests/e2e/_serve.py.
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.accounts_payable]

AP_CREATE = '/accounts-payable/create'
VENDOR_SCOPE = '.choices:has(#payee)'
DROPDOWN = VENDOR_SCOPE + ' .choices__list--dropdown'


def _open_vendor_picker(page, e2e_server):
    """Land on the AP form with the vendor picker open and its list rendered."""
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#payee', state='attached')
    scope = page.locator(VENDOR_SCOPE)
    scope.locator('.choices__inner').click()
    page.wait_for_selector(DROPDOWN + ' .choices__item')
    return scope


# Choices renders the "Search or select a payee..." placeholder as a chip too,
# so "nothing selected" is the absence of a NON-placeholder chip, not an empty box.
SELECTED_CHIP = '.choices__list--single .choices__item:not(.choices__placeholder)'
VENDOR_CHIP = VENDOR_SCOPE + ' ' + SELECTED_CHIP

# The AP form carries several pickers, so every DOM probe must be SCOPED to the
# vendor one -- an unscoped document.querySelector reads whichever chip happens
# to come first in the page and silently asserts about the wrong field.
_WAIT_VENDOR_CHIP = """txt => {
    const picker = document.querySelector('#payee').closest('.choices');
    const chip = picker && picker.querySelector(
        '.choices__list--single .choices__item:not(.choices__placeholder)');
    return !!(chip && chip.textContent.includes(txt));
}"""


def _selected_label(scope):
    """The text of the picker's selected chip ('' when nothing is selected)."""
    chip = scope.locator(SELECTED_CHIP)
    return chip.first.inner_text().strip() if chip.count() else ''


def test_tab_selects_the_highlighted_match_after_typing(logged_in_page, e2e_server):
    """Type enough to single out V002, press Tab -> V002 is the selected vendor."""
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    page.keyboard.type('V002')
    page.wait_for_selector(DROPDOWN + ' .choices__item--selectable.is-highlighted')
    page.keyboard.press('Tab')

    page.wait_for_function(_WAIT_VENDOR_CHIP, arg='V002')
    assert 'V002' in _selected_label(scope)
    assert page.locator('#payee').input_value() != '', \
        'Tab committed a visible chip but left the underlying <select> empty'


def test_tab_commits_the_value_to_the_underlying_select(logged_in_page, e2e_server):
    """The chip is cosmetic -- the POSTed value is the <select>'s, so assert it."""
    page = logged_in_page
    _open_vendor_picker(page, e2e_server)

    expected = page.eval_on_selector(
        '#payee',
        """el => {
            const c = Array.from(el.closest('.choices')
                .querySelectorAll('.choices__list--dropdown .choices__item--selectable'))
                .find(i => i.textContent.includes('V003'));
            return c ? c.getAttribute('data-value') : null;
        }"""
    )
    assert expected, 'V003 is not in the seeded vendor list -- fixture drift'

    page.keyboard.type('V003')
    page.wait_for_selector(DROPDOWN + ' .choices__item--selectable.is-highlighted')
    page.keyboard.press('Tab')

    page.wait_for_function(
        "v => document.querySelector('#payee').value === v", arg=expected
    )
    assert page.locator('#payee').input_value() == expected


def test_tab_moves_focus_out_of_the_picker(logged_in_page, e2e_server):
    """Tab must still tab -- selecting cannot swallow the focus move."""
    page = logged_in_page
    _open_vendor_picker(page, e2e_server)

    page.keyboard.type('V002')
    page.wait_for_selector(DROPDOWN + ' .choices__item--selectable.is-highlighted')
    page.keyboard.press('Tab')
    page.wait_for_function(_WAIT_VENDOR_CHIP, arg='V002')

    where = page.evaluate(
        """() => {
            const el = document.activeElement;
            const picker = document.querySelector('#payee').closest('.choices');
            if (!el) return 'none';
            if (picker && picker.contains(el)) return 'picker';
            if (el === document.body) return 'body';
            return 'moved-on';
        }"""
    )
    # 'body' is the failure this guards: committing the choice SYNCHRONOUSLY hides
    # the dropdown that holds the focused search input, so the element the browser
    # was about to Tab from disappears mid-keydown and focus falls to <body> --
    # the next Tab then restarts from the top of the document.
    assert where == 'moved-on', (
        f'after Tab, focus was {where!r}; expected the next field'
    )


def test_tab_after_escape_does_not_select(logged_in_page, e2e_server):
    """CONTROL for the open-dropdown gate.

    Escape closes the dropdown but Choices LEAVES the highlight on the row in
    the DOM (measured), so "nothing is highlighted" is not what protects this --
    only the open check is. Arrow first, because after Escape the arrow is what
    still marks the choice as expressed; a typed query is cleared by Escape and
    would be caught by the expressed-choice gate instead, testing the wrong one.
    """
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    page.keyboard.press('ArrowDown')
    page.keyboard.press('ArrowDown')
    page.wait_for_selector(DROPDOWN + ' .choices__item--selectable.is-highlighted')
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)
    assert not page.evaluate(
        "() => document.querySelector('#payee').closest('.choices')"
        ".querySelector('.choices__list--dropdown').classList.contains('is-active')"
    ), 'Escape did not close the dropdown -- this test is not testing the open gate'

    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert _selected_label(scope) == '',         f'Tab selected {_selected_label(scope)!r} with the dropdown already closed'
    assert page.locator('#payee').input_value() == ''


def test_tab_after_clearing_the_query_does_not_select(logged_in_page, e2e_server):
    """CONTROL for the expressed-choice gate.

    Backspacing a query away leaves the dropdown open with a REAL vendor still
    highlighted (measured: V001, the first row of the restored full list). The
    user deleted what they typed -- committing that leftover row on Tab would
    write a vendor they never chose.
    """
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    page.keyboard.type('V003')
    page.wait_for_selector(DROPDOWN + ' .choices__item--selectable.is-highlighted')
    for _ in range(8):
        page.keyboard.press('Backspace')
    page.wait_for_timeout(300)
    live = page.evaluate(
        """() => {
            const hl = document.querySelector('#payee').closest('.choices')
                .querySelector('.choices__list--dropdown .choices__item--selectable.is-highlighted');
            return hl ? hl.getAttribute('data-value') : null;
        }"""
    )
    assert live, 'no row is highlighted after clearing -- this test proves nothing'

    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert _selected_label(scope) == '',         f'Tab committed {_selected_label(scope)!r} after the query was deleted'
    assert page.locator('#payee').input_value() == ''


def test_arrowing_then_reopening_does_not_carry_the_choice_over(logged_in_page, e2e_server):
    """CONTROL for resetting the expressed-choice flag on each open.

    Arrow (expressed), Escape, reopen: the highlight survives in the DOM, so if
    the flag were not cleared on open, an untouched second visit to the picker
    would commit that stale row on Tab.
    """
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    page.keyboard.press('ArrowDown')
    page.keyboard.press('ArrowDown')
    page.wait_for_selector(DROPDOWN + ' .choices__item--selectable.is-highlighted')
    page.keyboard.press('Escape')
    page.wait_for_timeout(200)

    scope.locator('.choices__inner').click()          # reopen, touch nothing
    page.wait_for_selector(DROPDOWN + ' .choices__item')
    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert _selected_label(scope) == '',         f'a stale highlight from an earlier open was committed: {_selected_label(scope)!r}'
    assert page.locator('#payee').input_value() == ''


def test_tab_on_the_add_action_does_not_select_or_open_the_modal(logged_in_page, e2e_server):
    """Tabbing off the pinned "Add Vendor..." row must not fire the quick-add modal."""
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    page.keyboard.press('ArrowDown')          # lands on the pinned add-action
    highlighted = page.locator(
        DROPDOWN + ' .choices__item--selectable.is-highlighted').first.inner_text().strip()
    assert 'Add Vendor' in highlighted, f'expected the add-action first, got {highlighted!r}'

    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert _selected_label(scope) == '',         f'Tab committed the add-action as a vendor: {_selected_label(scope)!r}'
    assert page.locator('#payee').input_value() == ''


def test_shift_tab_does_not_select(logged_in_page, e2e_server):
    """Only forward Tab commits -- tabbing BACKWARDS out is an escape hatch."""
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    page.keyboard.type('V002')
    page.wait_for_selector(DROPDOWN + ' .choices__item--selectable.is-highlighted')
    page.keyboard.press('Shift+Tab')
    page.wait_for_timeout(300)

    assert _selected_label(scope) == '',         f'Shift+Tab committed {_selected_label(scope)!r}'


def test_tab_after_arrow_navigation_selects_the_highlighted_row(logged_in_page, e2e_server):
    """No typing, but the user moved the highlight -- that IS an expressed choice."""
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    # The first row is the pinned "Add Vendor..." action; arrow past it to a
    # real vendor -- Tab must never fire a quick-add modal (see the JS guard).
    page.keyboard.press('ArrowDown')
    page.keyboard.press('ArrowDown')
    page.wait_for_selector(DROPDOWN + ' .choices__item--selectable.is-highlighted')
    highlighted = page.locator(
        DROPDOWN + ' .choices__item--selectable.is-highlighted').first.inner_text().strip()
    assert 'Add Vendor' not in highlighted, 'arrowed onto the add-action, not a vendor'

    page.keyboard.press('Tab')
    page.wait_for_selector(VENDOR_CHIP)
    assert highlighted in _selected_label(scope)


def test_tab_without_typing_or_arrowing_does_not_select(logged_in_page, e2e_server):
    """CONTROL: opening a picker and tabbing straight out must select nothing."""
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    before = _selected_label(scope)
    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert _selected_label(scope) == before, (
        'tabbing out of an untouched picker silently selected '
        f'{_selected_label(scope)!r} -- a value the user never chose'
    )
    assert page.locator('#payee').input_value() == '', \
        'tabbing out of an untouched picker wrote a value into the <select>'


def test_tab_on_a_query_matching_nothing_does_not_select(logged_in_page, e2e_server):
    """CONTROL: no match means no highlight means nothing to commit."""
    page = logged_in_page
    scope = _open_vendor_picker(page, e2e_server)

    page.keyboard.type('zzzznotavendor')
    page.wait_for_selector(DROPDOWN + ' .search-select-noresults')
    page.keyboard.press('Tab')
    page.wait_for_timeout(300)

    assert _selected_label(scope) == '', \
        f'a no-match query still committed {_selected_label(scope)!r} on Tab'
    assert page.locator('#payee').input_value() == ''
