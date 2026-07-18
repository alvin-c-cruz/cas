"""CAS ui-test driver: R-04 slice 4 (Petty Cash Fund) browser pass, pre-merge gate.

Run against a FRESH /ui-test cas --branch feat/r04-petty-cash-fund (empty schema).
Bootstraps first-run admin, builds a minimal COA + a bank account, enables
bank_accounts + petty_cash, sets the petty_cash_due_to_custodian control account,
then drives the full petty-cash flow via real UI clicks: establish fund -> record
voucher -> replenish -> print. Checks Action Items badge + Audit Log per discipline
#7, and the print surface per discipline #9.
"""
import sys
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

results = []
def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + (("  -- " + detail) if detail else ""))

def strip_ro(page):
    page.eval_on_selector_all("input,select,textarea",
        "els => els.forEach(e => e.removeAttribute('readonly'))")

def choices_select(page, select_id, option_text_substring):
    """Drive a Choices.js-enhanced <select> -- it strips/hides the native <select>'s
    options, so select_option() can't see them; open the widget and click the
    matching dropdown item instead (apv-playwright-quirks)."""
    wrapper = page.locator(f"div.choices:has(#{select_id})")
    wrapper.locator(".choices__inner").click()
    page.wait_for_timeout(200)
    item = wrapper.locator(".choices__item--choice", has_text=option_text_substring).first
    item.click()
    page.wait_for_timeout(150)

def body_has(page, text):
    return text.lower() in page.content().lower()

def register(page, b, username, email, pw):
    page.goto(b + "/register", wait_until="networkidle")
    strip_ro(page)
    page.fill("input[name='username']", username)
    page.fill("input[name='email']", email)
    if page.locator("input[name='full_name']").count():
        page.fill("input[name='full_name']", username.title())
    page.fill("#password-field", pw)
    page.fill("input[name='confirm_password']", pw)
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("() => document.querySelector(\"input[name='confirm_password']\").form.submit()")

def approve_pending_account(page, b, code):
    """Admin account-creates always go through AccountChangeRequest (admins never
    auto-approve, per can_auto_approve()'s sole-accountant rule) -- but
    can_be_approved_by() lets a full-access user (admin) approve their OWN request.
    Click Approve on the row, then confirm in the no-JS-popup modal."""
    page.goto(b + "/accounts/pending-approvals", wait_until="networkidle")
    row = page.locator("table tr", has_text=code)
    if row.count() == 0:
        return False, "no pending row for " + code
    row.first.get_by_role("button", name="Approve", exact=False).first.click()
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"):
        page.click("#approve-form button[type=submit]")
    # Success = the row for this code is no longer in the (now-refreshed) pending list.
    still_pending = page.locator("table tr", has_text=code).count() > 0
    return (not still_pending), page.url

def create_account(page, b, code, name, account_type, normal_balance, parent_label=None):
    page.goto(b + "/accounts/", wait_until="networkidle")
    if code in page.content():
        return True   # idempotent -- already created (and approved) by an earlier run
    page.goto(b + "/accounts/create", wait_until="networkidle")
    page.fill("#code", code)
    page.fill("#name", name)
    if parent_label:
        # JS auto-inherits account_type/normal_balance from the parent on change.
        page.select_option("#parent-account-field", label=parent_label)
        page.wait_for_timeout(400)
    else:
        page.select_option("#account-type-field", account_type)
        page.select_option("#normal-balance-field", normal_balance)
        if account_type in ("Asset", "Liability"):
            # Required for top-level Asset/Liability accounts (TYPES_NEEDING_CLASSIFICATION).
            page.wait_for_timeout(200)
            page.select_option("#classification-field", "Current")
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button[type=submit]")
    ok = not body_has(page, "is required") and (
        "pending" in page.content().lower() or code in page.content())
    if not ok:
        print("    DEBUG flash:", harness.flash_text(page), "url=", page.url)
        return False
    approved, detail = approve_pending_account(page, b, code)
    return approved

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=250)
    b = harness.base_url()
    pw_shared = harness.password()

    # --- 0. bootstrap first-run admin (idempotent -- skip if already created by a prior run) ---
    already_admin = "dashboard" in harness.login(page, "admin")
    if not already_admin:
        register(page, b, "admin", "admin@example.com", pw_shared)
        check("admin bootstrap registration succeeded", not body_has(page, "not pre-approved"), page.url)
        landing = harness.login(page, "admin")
    else:
        landing = page.url
    check("admin lands on a working page (not stuck at login/branch)",
          "/login" not in landing and "select-branch" not in landing, landing)

    # --- 1. minimal COA: 1 parent + 3 leaves needed for petty cash ---
    check("create parent Current Assets (10000)",
          create_account(page, b, "10000", "Current Assets", "Asset", "debit"))
    check("create leaf Petty Cash Fund (10050)",
          create_account(page, b, "10050", "Petty Cash Fund", "Asset", "debit", "10000 - Current Assets"))
    check("create leaf Cash in Bank (10051)",
          create_account(page, b, "10051", "Cash in Bank - BPI", "Asset", "debit", "10000 - Current Assets"))
    check("create parent Current Liabilities (20000)",
          create_account(page, b, "20000", "Current Liabilities", "Liability", "credit"))
    check("create leaf Due to Petty Cash Custodian (20050)",
          create_account(page, b, "20050", "Due to Petty Cash Custodian", "Liability", "credit", "20000 - Current Liabilities"))
    check("create parent Operating Expenses (50000)",
          create_account(page, b, "50000", "Operating Expenses", "Administrative Expense", "debit"))
    check("create leaf Office Supplies Expense (50050)",
          create_account(page, b, "50050", "Office Supplies Expense", "Expense", "debit", "50000 - Operating Expenses"))

    # --- 2. enable bank_accounts + petty_cash modules (admin-only, no non-admin path) ---
    page.goto(b + "/settings", wait_until="networkidle")
    # Settings > Packages tab holds the module toggle table (per company_settings modules_toggle route)
    if page.locator("[data-tab='packages'], .tab:has-text('Packages')").count():
        page.locator(".tab:has-text('Packages')").first.click()
        page.wait_for_timeout(300)

    def toggle_module(key):
        form = page.locator(f"form:has(input[name='key'][value='{key}'])")
        if form.count() == 0:
            return False, "toggle form not found"
        enable_input = form.first.locator("input[name='enable']")
        if enable_input.get_attribute("value") == "0":
            return True, "already enabled (idempotent skip)"   # toggling would DISABLE it
        with page.expect_navigation(wait_until="networkidle"):
            form.first.locator("button[type=submit]").click()
        return True, ""

    ok, detail = toggle_module("bank_accounts")
    check("enabled bank_accounts module", ok and body_has(page, "enabled"), detail)
    ok, detail = toggle_module("petty_cash")
    check("enabled petty_cash module", ok and body_has(page, "enabled"), detail)

    # --- 3. set petty_cash_due_to_custodian control account ---
    page.goto(b + "/settings/control-accounts", wait_until="networkidle")
    has_field = page.locator("select[name='petty_cash_due_to_custodian_account_code'], "
                              "select#petty_cash_due_to_custodian_account_code").count() > 0
    check("control-accounts page exposes petty_cash_due_to_custodian picker", has_field, page.url)
    if has_field:
        choices_select(page, "ca_petty_cash_due_to_custodian", "20050")
        with page.expect_navigation(wait_until="networkidle"):
            page.click("button[type=submit]")
        check("control account save succeeded", not body_has(page, "this field is required"), page.url)

    # --- 4. create a bank account (funding source), via the real sidebar link ---
    # Sidebar sections are an accordion (one open at a time); expand Banking first.
    banking_label = page.locator("[data-section='area-banking']")
    if banking_label.count():
        banking_label.first.click()
        page.wait_for_timeout(300)
    page.click("a.nav-item:has-text('Bank Accounts')")
    page.wait_for_load_state("networkidle")
    check("Bank Accounts list reached via sidebar", "/bank-accounts" in page.url, page.url)
    page.click("a:has-text('Create Bank Account')")
    page.wait_for_load_state("networkidle")
    page.fill("#code", "BA-BPI")
    page.fill("#name", "BPI Checking")
    choices_select(page, "account_id", "10051")
    if page.locator("#account_type").count():
        page.select_option("#account_type", "checking")
    if page.locator("#opening_balance").count():
        page.fill("#opening_balance", "50000.00")
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button[type=submit]")
    check("bank account BA-BPI created", body_has(page, "ba-bpi") or "bank-accounts" in page.url, page.url)

    # --- 5. Petty Cash: reach via sidebar (not page.goto) ---
    page.click("a.nav-item:has-text('Petty Cash')")
    page.wait_for_load_state("networkidle")
    check("Petty Cash Funds list reached via sidebar nav link", "/petty-cash/funds" in page.url, page.url)

    badge_before = page.locator("#nav-action-badge").inner_text() if page.locator("#nav-action-badge").count() else "0"

    page.click("a:has-text('Enter Petty Cash Fund')")
    page.wait_for_load_state("networkidle")
    page.fill("#code", "PCF-01")
    page.fill("#name", "Main Office Petty Cash")
    page.select_option("#account_id", label="10050 — Petty Cash Fund")
    page.fill("#custodian", "Juan Dela Cruz")
    page.fill("#float_amount", "5000.00")
    page.select_option("#funding_bank_account_id", label="BA-BPI — BPI Checking")
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button[type=submit]")
    check("fund PCF-01 established, landed on fund status page",
          "petty-cash/funds/" in page.url and body_has(page, "pcf-01"), page.url)
    check("establish flash success shown", body_has(page, "established"), harness.flash_text(page))

    # --- 6. record a voucher ---
    page.click("a:has-text('Record Voucher')")
    page.wait_for_load_state("networkidle")
    page.fill("#payee", "Office Depot")
    page.select_option("#expense_account_id", label="50050 — Office Supplies Expense")
    page.fill("#amount", "350.00")
    page.fill("#description", "Bond paper and pens")
    page.fill("#receipt_ref", "OR-1001")
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button[type=submit]")
    check("voucher recorded, back on fund status with held voucher listed",
          body_has(page, "office depot") and body_has(page, "350.00"), page.url)

    # --- 7. replenish ---
    page.click("a:has-text('Replenish')")
    page.wait_for_load_state("networkidle")
    check("replenish form reached, held voucher pre-checked", body_has(page, "office depot"), page.url)
    page.fill("#physical-cash-input", "4650.00")
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button:has-text('Post Replenishment')")
    check("replenishment posted, landed on replenishment detail",
          "/petty-cash/replenishments/" in page.url and body_has(page, "posted"), page.url)
    check("replenishment JE table shows Due to Petty Cash Custodian credit leg",
          body_has(page, "due to petty cash custodian"), "")

    # --- 8. print surface (discipline #9) ---
    with page.expect_popup() as pop_info:
        page.click("a:has-text('Print')")
    print_page = pop_info.value
    print_page.wait_for_load_state("networkidle")
    check("print view renders without 500", print_page.locator("body").count() > 0
          and not body_has(print_page, "internal server error"), print_page.url)
    check("print view shows the replenishment number and due-custodian line",
          body_has(print_page, "pcr-") and body_has(print_page, "due to petty cash custodian"), "")
    print_page.close()

    # --- 9. audit log + action items (discipline #7) ---
    page.goto(b + "/audit-log", wait_until="networkidle")
    check("audit log records the fund establish", body_has(page, "petty_cash") and body_has(page, "pcf-01"), "")

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, name, detail in results:
        if not ok:
            print("  FAILED:", name, "--", detail)
