"""Shared DOM helpers for the Tab-to-select picker e2e tests.

Leading underscore so pytest does not collect this as a test module.

The vendor picker on the AP form is the subject; the AP form carries SEVERAL
Choices pickers, so every probe here is SCOPED to the vendor one. An unscoped
`document.querySelector('.choices__list--single .choices__item')` reads
whichever chip comes first in the page and silently asserts about the wrong
field -- that mistake made two of these tests pass for the wrong reason.
"""

AP_CREATE = '/accounts-payable/create'
VENDOR_SCOPE = '.choices:has(#payee)'
DROPDOWN = VENDOR_SCOPE + ' .choices__list--dropdown'
HIGHLIGHTED = DROPDOWN + ' .choices__item--selectable.is-highlighted'

# Choices renders the "Search or select a payee..." placeholder as a chip too,
# so "nothing selected" is the absence of a NON-placeholder chip, not an empty box.
SELECTED_CHIP = '.choices__list--single .choices__item:not(.choices__placeholder)'
VENDOR_CHIP = VENDOR_SCOPE + ' ' + SELECTED_CHIP

WAIT_VENDOR_CHIP = """txt => {
    const picker = document.querySelector('#payee').closest('.choices');
    const chip = picker && picker.querySelector(
        '.choices__list--single .choices__item:not(.choices__placeholder)');
    return !!(chip && chip.textContent.includes(txt));
}"""

HIGHLIGHTED_VALUE = """() => {
    const hl = document.querySelector('#payee').closest('.choices')
        .querySelector('.choices__list--dropdown .choices__item--selectable.is-highlighted');
    return hl ? hl.getAttribute('data-value') : null;
}"""

DROPDOWN_IS_OPEN = """() => document.querySelector('#payee').closest('.choices')
    .querySelector('.choices__list--dropdown').classList.contains('is-active')"""


def open_vendor_picker(page, e2e_server):
    """Land on the AP form with the vendor picker open and its list rendered."""
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#payee', state='attached')
    scope = page.locator(VENDOR_SCOPE)
    scope.locator('.choices__inner').click()
    page.wait_for_selector(DROPDOWN + ' .choices__item')
    return scope


def selected_label(scope):
    """The text of the picker's selected chip ('' when nothing is selected)."""
    chip = scope.locator(SELECTED_CHIP)
    return chip.first.inner_text().strip() if chip.count() else ''


def assert_nothing_selected(page, scope, why):
    """Both halves matter: the chip is what the user sees, the <select> is what POSTs."""
    label = selected_label(scope)
    assert label == '', f'{why}: Tab committed {label!r}'
    assert page.locator('#payee').input_value() == '', \
        f'{why}: Tab wrote a value into the underlying <select>'


def assert_real_row_highlighted(page, why):
    """Fail loudly when a do-not-commit test has nothing to commit.

    Choices re-renders asynchronously, so which row carries `.is-highlighted`
    at Tab time varies: it may be the placeholder (data-value ''), the pinned
    add-action, or a real vendor. Only the last case actually exercises the
    guard -- in the other two the commit is blocked by the empty/add value no
    matter what the guard does, and the test passes while proving nothing.
    This turns that silent pass into a visible failure.
    """
    value = page.evaluate(HIGHLIGHTED_VALUE)
    assert value, f'{why}: no row is highlighted, so this test proves nothing'
    assert not value.startswith('__add'), (
        f'{why}: the highlighted row is the add-action ({value!r}), which is '
        'blocked by its own guard -- this test proves nothing'
    )
    return value
