"""Registers the chief_accountant user 'uitest_ca' -- a standalone setup step, deliberately
split out of `_shared_setup_cas_scope.py`.

Run this AFTER `vt_wt_crud_cycle.py` and `customers_vendors_crud_cycle.py` (both need admin to
still be the SOLE active full-access user for their VAT/Sales-VAT/WHT creates to auto-approve --
see the ordering constraint in `_shared_setup_cas_scope.py`'s docstring), and BEFORE
`ca_registers_and_edits_perms.py` and `sales_invoice_crud_post.py` (both need uitest_ca to exist).

Full run order on a fresh provision:
    1. _shared_setup_cas_scope.py
    2. vt_wt_crud_cycle.py
    3. customers_vendors_crud_cycle.py
    4. this script (_register_ca.py)
    5. ca_registers_and_edits_perms.py
    6. sales_invoice_crud_post.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

TEST_PW = harness.password()


def login_as(page, b, username, password):
    page.goto(b + "/logout", wait_until="networkidle")
    page.goto(b + "/login", wait_until="networkidle")
    harness.strip_readonly(page, "#username, #password")
    page.fill("#username", username)
    page.fill("#password", password)
    page.press("#password", "Enter")
    page.wait_for_load_state("networkidle")


with sync_playwright() as pw:
    browser, page = harness.connect(pw)
    b = harness.base_url()

    print("=== register CA (uitest_ca) ===")
    login_as(page, b, "admin", TEST_PW)
    page.goto(b + "/approved-emails/add", wait_until="networkidle")
    page.fill("#email", "uitest_ca@example.com")
    page.select_option("#position", "chief_accountant")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    print("  approved-email:", harness.flash_text(page))

    page.goto(b + "/logout", wait_until="networkidle")
    page.goto(b + "/register", wait_until="networkidle")
    page.fill("#username", "uitest_ca")
    page.fill("#email", "uitest_ca@example.com")
    page.fill("#full_name", "UI Test Chief Accountant")
    page.fill("#password-field", TEST_PW)
    page.fill("#confirm_password", TEST_PW)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    print("  register:", harness.flash_text(page))

    print("\nDone. uitest_ca registered -- admin is no longer sole full-access from this point on.")
