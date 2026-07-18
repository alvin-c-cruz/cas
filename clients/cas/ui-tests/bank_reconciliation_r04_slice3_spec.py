"""CAS ui-test driver: R-04 slice 3 (Bank Reconciliation) browser pass, pre-merge gate.

Run against a FRESH /ui-test cas --branch feat/r04-bank-reconciliation (empty schema).
Bootstraps first-run admin, builds a minimal COA, enables bank_accounts +
bank_reconciliation, creates two bank accounts, posts an intra-branch Bank
Transfer between them (a real posted JE touching each account's GL account,
reusing already-shipped infra instead of fighting a dynamic JV line-item form),
then drives the full reconciliation flow via real UI clicks: start reconciliation
-> tick the transfer item -> post an inline adjustment -> complete -> detail -> print.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
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

def choices_select(page, select_id, option_text_substring):
    wrapper = page.locator(f"div.choices:has(#{select_id})")
    wrapper.locator(".choices__inner").click()
    page.wait_for_timeout(200)
    item = wrapper.locator(".choices__item--choice", has_text=option_text_substring).first
    item.click()
    page.wait_for_timeout(150)

def approve_pending_account(page, b, code):
    page.goto(b + "/accounts/pending-approvals", wait_until="networkidle")
    row = page.locator("table tr", has_text=code)
    if row.count() == 0:
        return False, "no pending row for " + code
    row.first.get_by_role("button", name="Approve", exact=False).first.click()
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"):
        page.click("#approve-form button[type=submit]")
    still_pending = page.locator("table tr", has_text=code).count() > 0
    return (not still_pending), page.url

def create_account(page, b, code, name, account_type, normal_balance, parent_label=None):
    page.goto(b + "/accounts/", wait_until="networkidle")
    table = page.locator("table tbody")
    if table.count() and code in table.inner_text():
        return True   # idempotent -- already created (and approved) by an earlier run
    page.goto(b + "/accounts/create", wait_until="networkidle")
    page.fill("#code", code)
    page.fill("#name", name)
    if parent_label:
        page.select_option("#parent-account-field", label=parent_label)
        page.wait_for_timeout(400)
    else:
        page.select_option("#account-type-field", account_type)
        page.select_option("#normal-balance-field", normal_balance)
        if account_type in ("Asset", "Liability"):
            page.wait_for_timeout(200)
            page.select_option("#classification-field", "Current")
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button[type=submit]")
    # Unambiguous success signal: the create view redirects to the accounts list on
    # success and RE-RENDERS accounts/form.html (URL stays at /accounts/create) on any
    # validation failure -- a content substring check on a short numeric code (e.g.
    # "10000") is not reliable, it can coincidentally match unrelated page boilerplate.
    ok = "/accounts/create" not in page.url
    if not ok:
        print("    DEBUG flash:", harness.flash_text(page), "url=", page.url)
        return False
    approved, detail = approve_pending_account(page, b, code)
    return approved

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=250)
    b = harness.base_url()
    pw_shared = harness.password()

    # --- 0. bootstrap first-run admin (idempotent) ---
    already_admin = "dashboard" in harness.login(page, "admin")
    if not already_admin:
        register(page, b, "admin", "admin@example.com", pw_shared)
        check("admin bootstrap registration succeeded", not body_has(page, "not pre-approved"), page.url)
        landing = harness.login(page, "admin")
    else:
        landing = page.url
    check("admin lands on a working page (not stuck at login/branch)",
          "/login" not in landing and "select-branch" not in landing, landing)

    # --- 1. minimal COA: 2 bank GL leaves + 1 expense leaf ---
    check("create parent Current Assets (10000)",
          create_account(page, b, "10000", "Current Assets", "Asset", "debit"))
    check("create leaf Cash in Bank - BPI (10051)",
          create_account(page, b, "10051", "Cash in Bank - BPI", "Asset", "debit", "10000 - Current Assets"))
    check("create leaf Cash in Bank - BDO (10052)",
          create_account(page, b, "10052", "Cash in Bank - BDO", "Asset", "debit", "10000 - Current Assets"))
    check("create parent Operating Expenses (50000)",
          create_account(page, b, "50000", "Operating Expenses", "Administrative Expense", "debit"))
    check("create leaf Bank Charges Expense (50060)",
          create_account(page, b, "50060", "Bank Charges Expense", "Administrative Expense", "debit", "50000 - Operating Expenses"))

    # --- 2. enable bank_accounts + bank_reconciliation modules ---
    page.goto(b + "/settings", wait_until="networkidle")
    if page.locator(".tab:has-text('Packages')").count():
        page.locator(".tab:has-text('Packages')").first.click()
        page.wait_for_timeout(300)

    def toggle_module(key):
        form = page.locator(f"form:has(input[name='key'][value='{key}'])")
        if form.count() == 0:
            return False, "toggle form not found"
        enable_input = form.first.locator("input[name='enable']")
        if enable_input.get_attribute("value") == "0":
            return True, "already enabled (idempotent skip)"
        with page.expect_navigation(wait_until="networkidle"):
            form.first.locator("button[type=submit]").click()
        return True, ""

    ok, detail = toggle_module("bank_accounts")
    check("enabled bank_accounts module", ok and body_has(page, "enabled"), detail)
    ok, detail = toggle_module("bank_transfers")
    check("enabled bank_transfers module (needed to generate a real posted JE to reconcile)",
          ok and body_has(page, "enabled"), detail)
    ok, detail = toggle_module("bank_reconciliation")
    check("enabled bank_reconciliation module", ok and body_has(page, "enabled"), detail)

    # --- 3. create two bank accounts (via sidebar, accordion expand first) ---
    banking_label = page.locator("[data-section='area-banking']")
    if banking_label.count():
        banking_label.first.click()
        page.wait_for_timeout(300)
    page.click("a.nav-item:has-text('Bank Accounts')")
    page.wait_for_load_state("networkidle")
    check("Bank Accounts list reached via sidebar", "/bank-accounts" in page.url, page.url)

    def create_bank_account(code, name, gl_code_substr):
        page.goto(b + "/bank-accounts/", wait_until="networkidle")
        if code in page.content():
            return True
        page.click("a:has-text('Create Bank Account')")
        page.wait_for_load_state("networkidle")
        page.fill("#code", code)
        page.fill("#name", name)
        choices_select(page, "account_id", gl_code_substr)
        if page.locator("#account_type").count():
            page.select_option("#account_type", "checking")
        if page.locator("#opening_balance").count():
            page.fill("#opening_balance", "0.00")
        with page.expect_navigation(wait_until="networkidle"):
            page.click("button[type=submit]")
        return code.lower() in page.content().lower() or "bank-accounts" in page.url

    check("bank account BA-BPI created", create_bank_account("BA-BPI", "BPI Checking", "10051"))
    check("bank account BA-BDO created", create_bank_account("BA-BDO", "BDO Checking", "10052"))

    # --- 4. post an intra-branch bank transfer BA-BPI -> BA-BDO (real posted JE
    #     touching both accounts' GL accounts, without fighting a dynamic JV form) ---
    page.goto(b + "/bank-transfers/", wait_until="networkidle")
    check("Bank Transfers list reached", "/bank-transfers" in page.url, page.url)
    page.click("a:has-text('Enter Bank Transfer')")
    page.wait_for_load_state("networkidle")
    if page.locator("#from_bank_account_id").count():
        choices_select(page, "from_bank_account_id", "BA-BPI")
        choices_select(page, "to_bank_account_id", "BA-BDO")
    page.fill("#amount", "5000.00")
    if page.locator("#transfer_date").count():
        page.fill("#transfer_date", "2026-06-15")
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button[type=submit]")
    check("bank transfer draft created", body_has(page, "5,000.00") or body_has(page, "5000.00"), page.url)
    if page.locator("button:has-text('Post')").count():
        with page.expect_navigation(wait_until="networkidle"):
            page.click("button:has-text('Post')")
        check("bank transfer posted", body_has(page, "completed") or body_has(page, "posted"), page.url)
    else:
        check("bank transfer posted", False, "no Post button found -- url=" + page.url)

    # --- 5. Bank Reconciliation: reach via sidebar, pick BA-BDO (the receiving leg) ---
    page.click("a.nav-item:has-text('Bank Reconciliation')")
    page.wait_for_load_state("networkidle")
    check("Bank Reconciliation landing reached via sidebar nav link", "/bank-reconciliation" in page.url, page.url)
    page.click("a:has-text('BA-BDO')")
    page.wait_for_load_state("networkidle")
    check("BA-BDO register reached", "/register" in page.url, page.url)

    page.click("a:has-text('Start Reconciliation')")
    page.wait_for_load_state("networkidle")
    page.fill("#statement_date", "2026-06-30")
    # 5000 (transfer deposit) - 25 (bank charge, added below) = 4975 statement ending balance --
    # set it up front so the flow balances to zero once both are ticked, same as a real
    # bank statement that already shows the charge.
    page.fill("#statement_ending_balance", "4975.00")
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button[type=submit]")
    check("draft reconciliation created, landed on work page", "/work" in page.url, page.url)

    # --- 6. work page: tick the transfer item ---
    check("work page shows the transfer's book item", body_has(page, "transfer") or body_has(page, "5,000.00"), page.url)
    checks = page.locator(".item-check")
    if checks.count() and not checks.first.is_checked():
        checks.first.check()
        page.wait_for_timeout(200)

    # --- 7. post an inline adjustment (bank charge), auto-clears itself ---
    adj_amount_field = page.locator("form[action*='add-adjustment'] input[name='amount']")
    if adj_amount_field.count():
        page.fill("form[action*='add-adjustment'] input[name='amount']", "25.00")
        page.fill("form[action*='add-adjustment'] input[name='description']", "Bank service charge")
        with page.expect_navigation(wait_until="networkidle"):
            page.click("form[action*='add-adjustment'] button[type=submit]")
        check("adjustment posted, flash shown", body_has(page, "adjustment posted"), harness.flash_text(page))
    else:
        check("adjustment form found", False, "no add-adjustment form on work page")

    # --- 8. re-tick the transfer item (page reloaded after the adjustment post) then check
    #     the live difference and complete ---
    checks2 = page.locator(".item-check")
    transfer_row = page.locator("tr", has_text="5,000.00")
    if transfer_row.count():
        cb = transfer_row.first.locator(".item-check")
        if cb.count() and not cb.first.is_checked():
            cb.first.check()
            page.wait_for_timeout(200)
    diff_text = page.locator("#stat-difference").inner_text()
    check("live difference reads zero once both items are ticked", "0.00" in diff_text, diff_text)

    with page.expect_navigation(wait_until="networkidle"):
        page.click("#complete-form button[type=submit]")
    completed = "/work" not in page.url
    check("reconciliation completed, landed on detail page", completed,
          harness.flash_text(page) if not completed else page.url)

    # --- 9. detail + print surfaces ---
    if "/bank-reconciliation/" in page.url:
        check("detail page shows Completed badge", body_has(page, "completed"), page.url)
        if page.locator("a:has-text('Print')").count():
            with page.expect_popup() as pop_info:
                page.click("a:has-text('Print')")
            print_page = pop_info.value
            print_page.wait_for_load_state("networkidle")
            check("print view renders without 500", not body_has(print_page, "internal server error"), print_page.url)
            check("print view shows BANK RECONCILIATION STATEMENT title",
                  body_has(print_page, "bank reconciliation statement"), "")
            print_page.close()
        else:
            check("print link present on detail page", False, "no Print link found")

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, name, detail in results:
        if not ok:
            print("  FAILED:", name, "--", detail)
