"""B5-W A in the browser: typing a DR number lower than the last one shows a hint beside DR #; saving still goes through.

Owner, typed in the root 23 Nov 2026: "B5-W A" -- "A hint beside DR # as soon as a lower number is typed: 'Lower than
the last DR number, 0275 -- fine if it is the paper's number'. Saving still goes through." The server side is
tests/integration/test_dr_number_lower_hint.py. Runs on the DR smoke's own seeded server (tests/e2e/test_dr_smoke.py),
whose only DR has a prefixed number (DR-E2E-0001), so the first test saves DR 0275 through the form.
"""
import pytest

from tests.e2e.test_dr_smoke import (CUSTOMER, SO_QTY, _save, _saved, dr_page, dr_server, pick,  # noqa: F401
                                     signed_in)

pytestmark = [pytest.mark.e2e, pytest.mark.delivery_receipts]

HINT = '#dr-number-hint'
LOWER = "Lower than the last DR number, 0275 — fine if it is the paper's number"


def _deliver(page, number):
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator(SO_QTY).first.fill('1')
    page.locator('#dr_number').fill(number)
    _save(page)
    return _saved(page)


def test_1_the_first_numbered_dr_saves_without_a_hint(dr_page):
    page = dr_page
    assert page.locator(HINT).count() == 0                   # nothing numbered yet: nothing to compare with
    assert '0275' in _deliver(page, '0275')


def test_2_a_lower_number_shows_the_hint_while_typing(dr_page):
    page = dr_page
    hint = page.locator(HINT)
    assert hint.is_hidden()                                  # the suggested next number is not lower
    page.locator('#dr_number').fill('0264')
    assert hint.is_visible() and hint.inner_text().strip() == LOWER
    page.locator('#dr_number').fill('0276')
    assert hint.is_hidden()
    page.locator('#dr_number').fill('264')                   # by value, not by its zeros
    assert hint.is_visible()
    page.locator('#dr_number').fill('DR-0001')               # not a plain number: no comparison
    assert hint.is_hidden()
    page.locator('#dr_number').fill('')
    assert hint.is_hidden()


def test_3_a_lower_number_still_saves(dr_page):
    page = dr_page
    page.locator('#dr_number').fill('0264')
    assert page.locator(HINT).is_visible()
    assert '0264' in _deliver(page, '0264')
