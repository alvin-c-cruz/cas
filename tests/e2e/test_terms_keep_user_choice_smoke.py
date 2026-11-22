"""
Playwright e2e smoke tests for A1 (22 Nov 2026): a Payment Terms the user chose is never replaced by the customer's
or vendor's default, on the Sales Order, Sales Invoice, Quotation and AP forms; on the SI and AP the due date follows
the chosen terms.

In the Philgen trial a term set before the customer (the dimmed header blocks the mouse, not the keyboard) was
replaced by the customer's default when the customer was chosen, and saved: Net 60 for a chosen Net 90.

Runs against its own seeded server (the Sales-cycle seed). The module adds a customer and a vendor whose default
terms are Net 60 through their own forms.
Run: pytest -m e2e tests/e2e/test_terms_keep_user_choice_smoke.py --browser-channel msedge
"""
import re
from datetime import date, timedelta

import pytest

from tests.e2e.conftest import _launch_seeded_server, _login_admin

pytestmark = [pytest.mark.e2e]

NET60_CUSTOMER = 'TERMS SIXTY TRADING'
NET60_VENDOR = 'TERMS SIXTY SUPPLY'


@pytest.fixture(scope='module')
def server(tmp_path_factory):
    yield from _launch_seeded_server(tmp_path_factory, {'E2E_SEED_PROFILE': 'sales'})


@pytest.fixture(scope='module')
def signed_in(browser, server):
    """One sign-in for the file (/login takes 10 a minute), and the Net 60 customer and vendor, made once."""
    context = browser.new_context()
    page = context.new_page()
    _login_admin(page, server)
    page.goto(server + '/customers/create')
    page.fill('#name', NET60_CUSTOMER)
    page.select_option('#payment_terms', 'Net 60')
    page.locator('form button[type="submit"]').first.click()
    page.wait_for_load_state('networkidle')
    page.goto(server + '/vendors/create')
    page.fill('#name', NET60_VENDOR)
    page.select_option('#payment_terms', 'Net 60')
    vat = _widget(page, '#default_vat_category')                    # required; a Choices widget
    vat.locator('.choices__inner').click()
    page.wait_for_timeout(250)
    vat.locator('.choices__list--dropdown .choices__item--selectable:not([data-value=""])').first.click()
    page.locator('form button[type="submit"]').first.click()
    page.wait_for_load_state('networkidle')
    state = context.storage_state()
    context.close()
    return state


@pytest.fixture
def page(browser, server, signed_in):
    context = browser.new_context(storage_state=signed_in, viewport={'width': 1400, 'height': 900})
    pg = context.new_page()
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    yield pg
    context.close()
    assert errors == [], errors


def _widget(page, css):
    return page.locator(css).locator(
        'xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " choices ")][1]')


def _pick(page, css, text):
    box = _widget(page, css)
    page.wait_for_timeout(250)
    if 'is-open' not in (box.get_attribute('class') or '').split():
        box.locator('.choices__inner').click()
        page.wait_for_timeout(250)
    box.locator('.choices__list--dropdown .choices__item--selectable', has_text=text).first.click()
    page.wait_for_timeout(250)


def _terms(page):
    return page.evaluate("""() => {
        const s = document.getElementById('payment_terms');
        const shown = s.closest('.choices').querySelector('.choices__list--single .choices__item');
        return [s.value, shown ? shown.textContent.trim() : ''];
    }""")


def _choose_terms_by_keyboard(page, term):
    """As a user can before the customer: the dimmed header lets no click through, but the keyboard reaches the
    picker. Open it, move down to the term, Enter."""
    _widget(page, '#payment_terms').focus()
    page.keyboard.press('Enter')
    page.wait_for_timeout(200)
    for _ in range(12):
        lit = page.evaluate("""() => { const h = document.getElementById('payment_terms').closest('.choices')
            .querySelector('.choices__list--dropdown .is-highlighted'); return h ? h.textContent.trim() : ''; }""")
        if lit == term:
            break
        page.keyboard.press('ArrowDown')
        page.wait_for_timeout(80)
    page.keyboard.press('Enter')
    page.wait_for_timeout(250)
    assert _terms(page) == [term, term]


def _days_after(iso, days):
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


# --- Sales Order ---------------------------------------------------------------------------------------------------

def test_so_a_term_chosen_before_the_customer_is_kept_and_saved(page, server):
    page.goto(server + '/sales-orders/create')
    page.wait_for_load_state('networkidle')
    _choose_terms_by_keyboard(page, 'Net 90')
    _pick(page, '#customer_id_display', NET60_CUSTOMER)
    page.wait_for_selector('#lineItemsSection', state='visible')
    page.wait_for_timeout(500)
    assert _terms(page) == ['Net 90', 'Net 90']
    _pick(page, '#prod-sel-1', 'Widget Standard')
    page.fill('#qty-1', '10')
    page.locator('#qty-1').blur()
    page.locator('#soForm button[type="submit"]').first.click()
    page.wait_for_url(re.compile(r'/sales-orders/\d+/edit$'), timeout=15000)   # a saved draft opens for editing
    page.wait_for_load_state('networkidle')
    assert _terms(page) == ['Net 90', 'Net 90']                                    # as stored


def test_so_an_untouched_term_takes_the_customers_default(page, server):
    page.goto(server + '/sales-orders/create')
    page.wait_for_load_state('networkidle')
    _pick(page, '#customer_id_display', NET60_CUSTOMER)
    page.wait_for_selector('#lineItemsSection', state='visible')
    page.wait_for_timeout(500)
    assert _terms(page) == ['Net 60', 'Net 60']


def test_so_a_chosen_term_survives_a_change_of_customer(page, server):
    page.goto(server + '/sales-orders/create')
    page.wait_for_load_state('networkidle')
    _pick(page, '#customer_id_display', NET60_CUSTOMER)
    page.wait_for_selector('#lineItemsSection', state='visible')
    page.wait_for_timeout(500)
    _pick(page, '#payment_terms', 'Net 90')
    _pick(page, '#customer_id_display', 'Acme Customer Inc')
    page.wait_for_timeout(800)
    assert _terms(page) == ['Net 90', 'Net 90']


# --- Sales Invoice -------------------------------------------------------------------------------------------------

def test_si_a_term_chosen_before_the_customer_is_kept_and_the_due_date_follows_it(page, server):
    page.goto(server + '/sales-invoices/create')
    page.wait_for_load_state('networkidle')
    _choose_terms_by_keyboard(page, 'Net 90')
    _pick(page, '#customer_id', NET60_CUSTOMER)
    page.wait_for_timeout(800)
    assert _terms(page) == ['Net 90', 'Net 90']
    invoice_date = page.locator('#invoice_date').input_value()
    assert page.locator('#due_date').input_value() == _days_after(invoice_date, 90)


def test_si_the_due_date_follows_a_change_of_terms(page, server):
    page.goto(server + '/sales-invoices/create')
    page.wait_for_load_state('networkidle')
    _pick(page, '#customer_id', NET60_CUSTOMER)
    page.wait_for_timeout(800)
    invoice_date = page.locator('#invoice_date').input_value()
    assert _terms(page) == ['Net 60', 'Net 60']
    assert page.locator('#due_date').input_value() == _days_after(invoice_date, 60)
    _pick(page, '#payment_terms', 'Net 90')
    assert page.locator('#due_date').input_value() == _days_after(invoice_date, 90)


# --- Quotation -----------------------------------------------------------------------------------------------------

def test_quotation_a_term_chosen_before_the_customer_is_kept(page, server):
    page.goto(server + '/quotations/create')
    page.wait_for_load_state('networkidle')
    _choose_terms_by_keyboard(page, 'Net 90')
    _pick(page, '#customer_id_display', NET60_CUSTOMER)
    page.wait_for_timeout(800)
    assert _terms(page) == ['Net 90', 'Net 90']


# --- AP voucher ----------------------------------------------------------------------------------------------------

def test_ap_a_term_chosen_before_the_vendor_is_kept_and_the_due_date_follows_it(page, server):
    page.goto(server + '/accounts-payable/create')
    page.wait_for_load_state('networkidle')
    _choose_terms_by_keyboard(page, 'Net 90')
    _pick(page, '#payee', NET60_VENDOR)
    page.wait_for_timeout(800)
    assert _terms(page) == ['Net 90', 'Net 90']
    base = page.locator('#vendor_invoice_date').input_value() or page.locator('#ap_date').input_value()
    assert page.locator('#due_date').input_value() == _days_after(base, 90)
