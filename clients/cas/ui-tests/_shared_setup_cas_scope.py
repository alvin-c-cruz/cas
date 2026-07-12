"""Shared setup for the CAS-scope regression specs (BUG-UITEST-SPECS-ASSUME-UNCAPTURED-SETUP).

Builds -- entirely through the UI, no direct DB writes -- the master data that
`vt_wt_crud_cycle.py`, `customers_vendors_crud_cycle.py`, and
`ca_registers_and_edits_perms.py` assume already exists on a fresh `/ui-test cas`
empty-schema provision. Run this ONCE, right after provisioning, before any of
those three specs.

Builds:
  - A throwaway 'accountant' user (uitest_setup_acct) used only to fast-build the
    COA via the sole-accountant auto-approve rule. Not referenced by any spec.
  - A 12-account COA (RIC-style: specific functional-category parents, no generic
    "Assets"/"Liabilities" blob -- memory `ric-coa-parent-account-convention`):
      1600 Trade Receivables -> 1610 Accounts Receivable - Trade
      1700 Prepaid Tax       -> 1710 Creditable Withholding Tax
                              -> 1720 Input Tax
      2100 Accounts Payable  -> 2110 Accounts Payable - Trade
      2300 Tax and Withholding Payables -> 2310 Output Tax Payable
                                        -> 2320 Withholding Tax Payable
      4100 Income            -> 4110 Sales Revenue
  - Purchase VAT category V12DG (12%, domestic_goods, input=1720)
  - Sales VAT category V12 "VATable Sales 12%" (12%, regular, output=2310)
  - Control Accounts: AR=1610, AP=2110, Creditable WHT=1710, WHT Payable=2320
  - The chief_accountant user 'uitest_ca' (needed by ca_registers_and_edits_perms.py)

ORDERING CONSTRAINT (see BUG-TAXMASTER-RATECHANGE-STUCK-SOLE-ADMIN and the
sole-full-access auto-approve rule in app/utils/admin_approval.py):
`vt_wt_crud_cycle.py` and `customers_vendors_crud_cycle.py` need ADMIN to be the
SOLE active full-access user for their VAT/Sales-VAT/WHT creates to auto-approve.
Once 'uitest_ca' exists, admin is no longer sole full-access, so those two specs'
tax-master creates would go PENDING instead -- breaking their assertions AND
leaving a stale pending request that blocks any retry (BUG-TAXMASTER-STALE-
PENDING-BLOCKS-RETRY). This script therefore builds the COA + VAT/Sales-VAT +
Control Accounts FIRST, and registers 'uitest_ca' LAST, after all of that is
already committed. Required run order for the 3 specs on a fresh provision:

    1. this script (_shared_setup_cas_scope.py)
    2. vt_wt_crud_cycle.py
    3. customers_vendors_crud_cycle.py
    4. ca_registers_and_edits_perms.py   (needs uitest_ca, built last above)

Scope note: this covers CAS-scope specs only. uom_products_crud_cycle.py,
quotation_crud_lifecycle.py, quotation_flow_inline_customer.py,
sales_order_crud_lifecycle.py, delivery_receipt_crud_lifecycle.py,
full_sales_area_as_ca.py, chief_accountant_role_crud.py, staff_sales_area_sod.py,
and accountant_sales_area_sod.py touch ERP-scope modules (Units of Measure,
Products, Quotations, Sales Orders, Delivery Receipts) and are OUT of scope for
this setup -- a separate ERP-scope fixture/setup is planned later (see
clients/cas/ui-tests/fixtures/README.md). full_sales_area_as_ca.py's own
assertion is additionally STALE (expects Sales Invoice creation to be blocked by
BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS, which is already fixed on main) -- flagged
in project-bug-tracker, not addressed by this script.
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


def pick_choices(page, name, needle):
    """Choices.js-enhanced select -- open + mousedown/click the choice (strips native options)."""
    wrap = page.locator(".choices:has(select[name='%s'])" % name)
    wrap.click()
    page.wait_for_timeout(250)
    opt = wrap.locator(".choices__list--dropdown .choices__item--choice", has_text=needle)
    opt.first.dispatch_event("mousedown")
    opt.first.dispatch_event("click")


def create_account(page, b, code, name, acct_type, classification, parent_label=None):
    page.goto(b + "/accounts/create", wait_until="networkidle")
    page.fill("#code", code)
    page.fill("#name", name)
    page.select_option("#account-type-field", acct_type)
    page.wait_for_timeout(150)
    if classification:
        page.select_option("#classification-field", classification)
    if parent_label:
        page.select_option("#parent-account-field", label=parent_label)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    print(f"  account {code} {name}: {harness.flash_text(page)!r}")


def toggle_module(page, b, key):
    page.goto(b + "/settings", wait_until="networkidle")
    page.click(".tab[data-tab-group='settings'][data-tab='packages']")
    page.wait_for_timeout(200)
    btn = page.locator(f"form:has(input[name='key'][value='{key}']) button[type=submit]")
    btn.click()
    page.wait_for_load_state("networkidle")
    print(f"  module {key}: {harness.flash_text(page)!r}")


with sync_playwright() as pw:
    browser, page = harness.connect(pw)
    b = harness.base_url()

    print("=== 1. temp accountant for fast COA auto-approve ===")
    login_as(page, b, "admin", TEST_PW)
    page.goto(b + "/approved-emails/add", wait_until="networkidle")
    page.fill("#email", "setupacct@example.com")
    page.select_option("#position", "accountant")
    cb = page.locator("input[name='book_chart_of_accounts']")
    if cb.count():
        cb.check()
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    print("  approved-email:", harness.flash_text(page))

    page.goto(b + "/logout", wait_until="networkidle")
    page.goto(b + "/register", wait_until="networkidle")
    page.fill("#username", "uitest_setup_acct")
    page.fill("#email", "setupacct@example.com")
    page.fill("#full_name", "UI Test Setup Accountant")
    page.fill("#password-field", TEST_PW)
    page.fill("#confirm_password", TEST_PW)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    print("  register:", harness.flash_text(page))

    print("=== 2. build the 12-account COA (auto-approved, sole accountant) ===")
    login_as(page, b, "uitest_setup_acct", TEST_PW)
    create_account(page, b, "1600", "Trade Receivables", "Asset", "Current")
    create_account(page, b, "1700", "Prepaid Tax", "Asset", "Current")
    create_account(page, b, "2100", "Accounts Payable", "Liability", "Current")
    create_account(page, b, "2300", "Tax and Withholding Payables", "Liability", "Current")
    create_account(page, b, "4100", "Income", "Revenue", "")

    create_account(page, b, "1610", "Accounts Receivable - Trade", "Asset", "Current", "1600 - Trade Receivables")
    create_account(page, b, "1710", "Creditable Withholding Tax", "Asset", "Current", "1700 - Prepaid Tax")
    create_account(page, b, "1720", "Input Tax", "Asset", "Current", "1700 - Prepaid Tax")
    create_account(page, b, "2110", "Accounts Payable - Trade", "Liability", "Current", "2100 - Accounts Payable")
    create_account(page, b, "2310", "Output Tax Payable", "Liability", "Current", "2300 - Tax and Withholding Payables")
    create_account(page, b, "2320", "Withholding Tax Payable", "Liability", "Current", "2300 - Tax and Withholding Payables")
    create_account(page, b, "4110", "Sales Revenue", "Revenue", "", "4100 - Income")

    print("=== 3. VAT categories + Control Accounts (admin still sole full-access) ===")
    login_as(page, b, "admin", TEST_PW)

    page.goto(b + "/vat-categories/create", wait_until="networkidle")
    page.fill("#code", "V12DG")
    page.fill("#name", "VAT 12% - Domestic Goods")
    page.fill("#rate", "12")
    page.select_option("#transaction_nature", "domestic_goods")
    pick_choices(page, "input_vat_account_id", "1720")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    print("  V12DG:", harness.flash_text(page))

    page.goto(b + "/sales-vat-categories/create", wait_until="networkidle")
    page.fill("#code", "V12")
    page.fill("#name", "VATable Sales 12%")
    page.fill("#rate", "12")
    page.select_option("#transaction_nature", "regular")
    pick_choices(page, "output_vat_account_id", "2310")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    print("  V12:", harness.flash_text(page))

    page.goto(b + "/settings/control-accounts", wait_until="networkidle")
    pick_choices(page, "ar_trade_account_code", "1610")
    pick_choices(page, "ap_trade_account_code", "2110")
    pick_choices(page, "creditable_wht_account_code", "1710")
    pick_choices(page, "wht_payable_account_code", "2320")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    print("  control accounts:", harness.flash_text(page))

    print("=== 4. register CA (uitest_ca) LAST -- see ordering constraint above ===")
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

    print("\nSetup complete. Run order: vt_wt_crud_cycle.py -> customers_vendors_crud_cycle.py -> ca_registers_and_edits_perms.py")
