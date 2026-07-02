# tests/e2e/test_opening_balances_smoke.py
"""Playwright e2e smoke for the Opening Balances line item — Choices.js account
search-select + Debit/Credit focus/blur formatting and Debit-XOR-Credit auto-clear.
These are JS-only behaviours pytest's HTML-only tests can't see.

Marked `opening_balances` so `pytest -m opening_balances` runs them.
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.opening_balances]

OB = '/opening-balances'
ROW = 'tr.ob-line'


def _first_row(page):
    return page.locator(ROW).first


def _pick_account(page, row, text):
    """Open the row's Choices account picker and click the option containing `text`."""
    row.locator('.choices__inner').click()
    page.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def test_account_is_search_select(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    assert _first_row(page).locator('.choices').count() == 1


def test_debit_blurs_to_formatted_amount(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    row = _first_row(page)
    deb = row.locator('.ob-debit')
    deb.click()
    deb.fill('5000')
    row.locator('.ob-credit').click()          # blur the debit field
    assert deb.input_value() == '5,000.00'


def test_entering_debit_clears_credit(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    row = _first_row(page)
    deb = row.locator('.ob-debit')
    cred = row.locator('.ob-credit')
    cred.click(); cred.fill('200'); deb.click()      # blur credit
    assert cred.input_value() == '200.00'
    deb.fill('5000'); cred.click()                   # blur debit -> credit clears
    assert deb.input_value() == '5,000.00'
    assert cred.input_value() == ''


def test_add_and_remove_line(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    assert page.locator(ROW).count() == 1
    page.click('#ob-add-row')
    assert page.locator(ROW).count() == 2
    assert page.locator(ROW).nth(1).locator('.choices').count() == 1
    page.locator(ROW).nth(1).locator('.ob-remove').click()
    assert page.locator(ROW).count() == 1


def test_save_draft_persists_formatted_row(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    row = _first_row(page)
    _pick_account(page, row, 'Cash on Hand')
    deb = row.locator('.ob-debit')
    deb.click(); deb.fill('5000'); row.locator('.ob-credit').click()
    page.click('#ob-form button[type="submit"]')
    page.wait_for_selector(ROW)
    assert _first_row(page).locator('.ob-debit').input_value() == '5,000.00'
