"""
Playwright e2e tests for TAB-TO-SELECT on the shared search-select picker
(app/static/search-select.js::initSearchSelect) -- the COMMIT half.

While the dropdown is OPEN, pressing Tab commits the highlighted choice and
moves focus on to the next field: the data-entry flow is "type V002, Tab, keep
typing", no mouse and no Enter.

The cases where Tab must commit NOTHING live in
test_search_select_tab_gates.py. They are split across two modules on purpose:
the e2e server is module-scoped and degrades over a long run (see the note in
conftest.py), and 11 logins against one server times out the last test's
post-login wait.

Vendors V001-V004 are seeded by tests/e2e/_serve.py.
"""
import pytest

from tests.e2e._picker_helpers import (
    DROPDOWN, HIGHLIGHTED, VENDOR_CHIP, WAIT_VENDOR_CHIP,
    open_vendor_picker, selected_label,
)

pytestmark = [pytest.mark.e2e, pytest.mark.accounts_payable]


def test_tab_selects_the_highlighted_match_after_typing(logged_in_page, e2e_server):
    """Type enough to single out V002, press Tab -> V002 is the selected vendor."""
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.keyboard.type('V002')
    page.wait_for_selector(HIGHLIGHTED)
    page.keyboard.press('Tab')

    page.wait_for_function(WAIT_VENDOR_CHIP, arg='V002')
    assert 'V002' in selected_label(scope)
    assert page.locator('#payee').input_value() != '', \
        'Tab committed a visible chip but left the underlying <select> empty'


def test_tab_commits_the_value_to_the_underlying_select(logged_in_page, e2e_server):
    """The chip is cosmetic -- the POSTed value is the <select>'s, so assert it."""
    page = logged_in_page
    open_vendor_picker(page, e2e_server)

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
    page.wait_for_selector(HIGHLIGHTED)
    page.keyboard.press('Tab')

    page.wait_for_function(
        "v => document.querySelector('#payee').value === v", arg=expected
    )
    assert page.locator('#payee').input_value() == expected


def test_tab_moves_focus_out_of_the_picker(logged_in_page, e2e_server):
    """Tab must still tab -- committing the choice cannot swallow the focus move."""
    page = logged_in_page
    open_vendor_picker(page, e2e_server)

    page.keyboard.type('V002')
    page.wait_for_selector(HIGHLIGHTED)
    page.keyboard.press('Tab')
    page.wait_for_function(WAIT_VENDOR_CHIP, arg='V002')

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
    # 'picker' means the commit swallowed the Tab. 'body' means the focused
    # search input was destroyed by the commit before the browser could move
    # focus, so the NEXT Tab restarts from the top of the document -- worse than
    # not selecting at all, because it looks like it worked.
    assert where == 'moved-on', f'after Tab, focus was {where!r}; expected the next field'


def test_tab_after_arrow_navigation_selects_the_highlighted_row(logged_in_page, e2e_server):
    """No typing, but the user moved the highlight -- that IS an expressed choice."""
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    # Row 1 is the pinned "Add Vendor..." action; arrow past it to a real vendor.
    page.keyboard.press('ArrowDown')
    page.keyboard.press('ArrowDown')
    page.wait_for_selector(HIGHLIGHTED)
    highlighted = page.locator(HIGHLIGHTED).first.inner_text().strip()
    assert 'Add Vendor' not in highlighted, 'arrowed onto the add-action, not a vendor'

    page.keyboard.press('Tab')
    page.wait_for_selector(VENDOR_CHIP)
    assert highlighted in selected_label(scope)


def test_typing_a_full_code_then_tab_leaves_the_dropdown_closed(logged_in_page, e2e_server):
    """After a commit the picker is finished with -- it must not stay open."""
    page = logged_in_page
    open_vendor_picker(page, e2e_server)

    page.keyboard.type('V002')
    page.wait_for_selector(HIGHLIGHTED)
    page.keyboard.press('Tab')
    page.wait_for_function(WAIT_VENDOR_CHIP, arg='V002')

    page.wait_for_selector(DROPDOWN + '.is-active', state='detached')


def test_tab_selection_notifies_everything_that_depends_on_it(logged_in_page, e2e_server):
    """Setting the value is not selecting -- the page has to be TOLD.

    Reported from the live AP form: Tab picked the vendor and drew the chip, but
    the voucher stayed locked at "Select a payee above to add line items". The
    select's value, selectedIndex and option text were byte-identical to the
    Enter path; the only difference was that no `change` event fired, so none of
    the work hanging off it ran -- vendor defaults, the line-item unlock, the
    PO/RR billing picker, the notes autofill.

    Choices' setChoiceByValue() does not dispatch change in this build, so the
    commit has to. This asserts the OUTCOME a user sees rather than the event,
    because the event is the mechanism and the unlock is the point.
    """
    page = logged_in_page
    scope = open_vendor_picker(page, e2e_server)

    page.evaluate("""() => {
        window.__changes = [];
        const s = document.getElementById('payee');
        s.addEventListener('change', () => window.__changes.push(s.value));
    }""")

    page.keyboard.type('V002')
    page.wait_for_selector(HIGHLIGHTED)
    page.keyboard.press('Tab')
    page.wait_for_function(WAIT_VENDOR_CHIP, arg='V002')

    assert page.evaluate("() => window.__changes") != [], (
        'Tab set the value and drew the chip but fired no change event, so every '
        'handler hanging off the picker never ran'
    )
    assert 'V002' in selected_label(scope)
