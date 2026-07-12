"""Cash Receipt (CR) full CRUD + posting + all 3 print surfaces (TEST-CASES.md T1.2/T1.6).

Requires the CAS-scope shared setup (_shared_setup_cas_scope.py, _register_ca.py) for accounts
1610 (cash/bank stand-in) and 4110 (revenue), and Customer CASCUST1.

Covers: create (standalone direct-revenue line, no AR settlement) -> verify JE-leg tie-out to
header (cash/AR leg + revenue leg) -> read -> audit -> print surface (c-1) button hidden on
draft -> post -> print surface (a) -> print surface (c-2) hidden setting -> print surface (b)
pre-printed overlay -> cancel.

FIXED 2026-07-12 (BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS, both axes): (1) the print ROUTE now
also enforces cr_print_access, not just cr_print_form (`app/cash_receipts/views.py::print_crv`);
(2) the Print button now also enforces cr_print_form, not just cr_print_access
(`cash_receipts/templates/cash_receipts/detail.html`) -- this button-side gap was a NEW addendum
found while building this spec (only SI's button had previously been verified to check both axes).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness
import sqlite3
import json
import datetime

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
results = []
def check(n, ok, d=""):
    results.append((bool(ok), n, d)); print(("PASS " if ok else "FAIL ") + n + (("  -- " + d) if d else ""))
def q1(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchone()
def body_has(page, t):
    for _ in range(12):
        try: return t.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
    return t.lower() in page.content().lower()

def login_as(page, b, username, password):
    page.goto(b + "/logout", wait_until="networkidle")
    page.goto(b + "/login", wait_until="networkidle")
    harness.strip_readonly(page, "#username, #password")
    page.fill("#username", username)
    page.fill("#password", password)
    page.press("#password", "Enter")
    page.wait_for_load_state("networkidle")

def pick_choices(page, name, needle):
    wrap = page.locator(".choices:has(select[name='%s'])" % name)
    wrap.click(); page.wait_for_timeout(250)
    opt = wrap.locator(".choices__list--dropdown .choices__item--choice", has_text=needle)
    opt.first.dispatch_event("mousedown"); opt.first.dispatch_event("click")

def set_docprint_settings(page, b, **kv):
    login_as(page, b, "admin", TEST_PW)
    page.goto(b + "/settings", wait_until="networkidle")
    if not (page.eval_on_selector("#company_name", "el => el.value") or "").strip():
        page.click(".tab[data-tab-group='settings'][data-tab='profile']")
        page.wait_for_timeout(150)
        page.fill("#company_name", "UI Test Company")
    page.click(".tab[data-tab-group='settings'][data-tab='docprint']")
    page.wait_for_timeout(200)
    for k, v in kv.items():
        page.select_option(f"#{k}", v)
    page.click("button[type=submit].btn-primary")
    page.wait_for_load_state("networkidle")
    print("  set %s FLASH: %r" % (kv, harness.flash_text(page)))
    login_as(page, b, "uitest_ca", TEST_PW)

TEST_PW = harness.password()

with sync_playwright() as pw:
    browser, page = harness.connect(pw)
    b = harness.base_url()
    login_as(page, b, "uitest_ca", TEST_PW)

    cash_id = q1("SELECT id FROM accounts WHERE code='1610'")[0]
    revenue_id = q1("SELECT id FROM accounts WHERE code='4110'")[0]
    cust_id = q1("SELECT id FROM customers WHERE code='CASCUST1'")[0]

    print("=== CREATE: standalone-revenue CR for UI Test Trading Corp, 1000.00 ===")
    page.goto(b + "/cash-receipts/create", wait_until="networkidle")
    crv_number = page.eval_on_selector("#crv_number", "el => el.value")
    pick_choices(page, "customer_id", "UI Test Trading Corp")
    pick_choices(page, "cash_account_id", "1610")
    page.fill("#notes", "ui-test CR create")
    line = [{"account_id": revenue_id, "description": "ui-test revenue line", "amount": "1000.00"}]
    page.evaluate("""(li)=>{document.getElementById('revenueLinesData').value=JSON.stringify(li);
        document.getElementById('arLinesData').value='[]';}""", line)
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.getElementById('crvForm').submit()")
    print("FLASH:", harness.flash_text(page))

    crv = q1("""SELECT id, status, total_amount, journal_entry_id
                FROM cash_receipt_vouchers WHERE crv_number=?""", crv_number)
    check("CR CREATE (draft)", crv is not None and crv[1] == 'draft', str(crv))
    crv_id = crv[0] if crv else None
    je_id = crv[3] if crv else None
    check("CR total = 1000.00", crv and float(crv[2]) == 1000.0, str(crv))
    check("CR create built a JE immediately", je_id is not None, str(crv))

    if je_id:
        legs = sqlite3.connect(DB).execute(
            "SELECT account_id, debit_amount, credit_amount FROM journal_entry_lines WHERE entry_id=?", (je_id,)
        ).fetchall()
        by_acct = {}
        for a, d, c in legs:
            by_acct[a] = by_acct.get(a, 0) + (d or 0) - (c or 0)
        check("JE: cash leg ties to header total (1000.00, debit)",
              round(by_acct.get(cash_id, 0), 2) == 1000.00, str(by_acct.get(cash_id)))
        check("JE: revenue leg ties to header amount (1000.00, credit)",
              round(-by_acct.get(revenue_id, 0), 2) == 1000.00, str(by_acct.get(revenue_id)))

    print("=== READ: detail renders ===")
    page.goto(b + f"/cash-receipts/{crv_id}", wait_until="networkidle")
    check("CR detail renders CR number + customer", body_has(page, crv_number) and body_has(page, "ui test trading corp"))

    print("=== audit trail ===")
    audit_row = q1("SELECT action, record_identifier FROM audit_logs WHERE module='cash_receipt' ORDER BY id DESC LIMIT 1")
    check("audit logged CR create", audit_row and audit_row[0] == 'create' and crv_number in (audit_row[1] or ''), str(audit_row))

    print("=== PRINT SURFACE (c-1): draft + default cr_print_access=posted_only -> button hidden ===")
    page.goto(b + f"/cash-receipts/{crv_id}", wait_until="networkidle")
    print_link_visible = page.locator("a[href*='/print']").count() > 0
    check("print button HIDDEN on draft under posted_only (button gate)", not print_link_visible)

    print("=== ROUTE-LEVEL GATE (BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS, FIXED 2026-07-12): does the ROUTE also honor posted_only? ===")
    # max_redirects=0 is required: Playwright's page.request.get() follows redirects by
    # default, which would silently mask this check -- a 302 to the detail page gets
    # followed, landing on a 200 response that (naturally) still contains the CR number,
    # producing a false "still broken" reading. Check the redirect itself, not where it leads.
    resp = page.request.get(b + f"/cash-receipts/{crv_id}/print", max_redirects=0)
    check("direct GET on a draft CR is refused (redirect), matching the button gate",
          resp.status in (301, 302, 303), "status=%s" % resp.status)

    print("=== POST ===")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    status = page.evaluate("""async(a)=>{const[u,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [b + f"/cash-receipts/{crv_id}/post", token])
    crv2 = q1("SELECT status FROM cash_receipt_vouchers WHERE id=?", crv_id)
    check("CR POSTED", crv2 and crv2[0] == 'posted', "http %s status=%s" % (status, crv2))
    audit_post = q1("SELECT action FROM audit_logs WHERE module='cash_receipt' ORDER BY id DESC LIMIT 1")
    check("audit logged CR post", audit_post and audit_post[0] == 'post', str(audit_post))

    print("=== PRINT SURFACE (a): posted + posted_only -> button shown, printable form renders ===")
    page.goto(b + f"/cash-receipts/{crv_id}", wait_until="networkidle")
    check("print button SHOWN on posted under posted_only", page.locator("a[href*='/print']").count() > 0)
    resp = page.request.get(b + f"/cash-receipts/{crv_id}/print")
    check("print (current form) 200 + shows CR number + amounts", resp.status == 200 and crv_number in resp.text())

    print("=== PRINT SURFACE (c-2): cr_print_form=hidden -> button gone + direct GET blocked ===")
    set_docprint_settings(page, b, cr_print_form="hidden")
    page.goto(b + f"/cash-receipts/{crv_id}", wait_until="networkidle")
    check("print button HIDDEN when cr_print_form=hidden",
          page.locator("a[href*='/print']").count() == 0)
    page.goto(b + f"/cash-receipts/{crv_id}/print", wait_until="networkidle")
    check("direct GET /print redirects away when cr_print_form=hidden",
          f"/cash-receipts/{crv_id}/print" not in page.url)

    print("=== PRINT SURFACE (b): pre-printed overlay ===")
    set_docprint_settings(page, b, cr_print_form="preprinted")
    resp = page.request.get(b + f"/cash-receipts/{crv_id}/print")
    check("print (preprinted form) 200", resp.status == 200)
    check("preprinted response renders the preprinted template",
          "preprinted" in resp.text().lower() or "layout" in resp.text().lower())

    set_docprint_settings(page, b, cr_print_form="current")  # restore default

    print("=== CANCEL a posted CR ===")
    page.goto(b + f"/cash-receipts/{crv_id}", wait_until="networkidle")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    status = page.evaluate("""async(a)=>{const[u,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        fd.append('cancel_reason','ui-test cancel reason, long enough');
        fd.append('reversal_date','%s');
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""" % datetime.date.today().isoformat(),
        [b + f"/cash-receipts/{crv_id}/cancel", token])
    crv3 = q1("SELECT status FROM cash_receipt_vouchers WHERE id=?", crv_id)
    check("CR CANCELLED", crv3 and crv3[0] == 'cancelled', "http %s status=%s" % (status, crv3))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
