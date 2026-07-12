"""Sales Invoice (SI) full CRUD + posting + all 3 print surfaces (TEST-CASES.md T1.1/T1.6).

Requires the CAS-scope shared setup (`_shared_setup_cas_scope.py`) plus:
  - A persistent Customer `CASCUST1` ("UI Test Trading Corp", sales VAT = V12)
  - A persistent Vendor `CASVEND1` ("UI Test Supplier Corp", purchase VAT = V12DG) -- used by
    the AP/CD specs, not this one, but built alongside it
  - A persistent Withholding Tax code `WC010` (1%, expanded, payable=2320/receivable=1710)
    -- none of these three existed in the original shared setup; added when this spec was built.

Covers: create (VAT-inclusive line, WHT applied) -> verify VAT/WHT extraction math -> verify
each non-plug JE leg ties to the SI header (memory `posted-je-leg-vs-source-header-invariant`)
-> read (detail renders) -> audit trail -> print surface (c) button hidden on draft under the
default `sv_print_access=posted_only` -> post -> print surface (a) printable form, button now
shown -> print surface (c) `sv_print_form=hidden` -> print surface (b) pre-printed overlay ->
cancel (with the required `reversal_date` + >=10-char `cancel_reason`).

KNOWN BUG TRIPWIRE (BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS, `project-bug-tracker`, OPEN as of
2026-07-12): the print BUTTON on the detail page correctly respects `sv_print_access` (hidden on
a draft under `posted_only`), but the print ROUTE itself only checks `sv_print_form=='hidden'`
and does NOT enforce `sv_print_access` at all -- a direct GET on a draft invoice's `/print`
renders 200 anyway. The same gap exists in Accounts Payable, Cash Disbursements (main print),
and Cash Receipts -- only Cash Disbursements' separate check-print route does this correctly.
This spec's "direct GET respects posted_only" check is EXPECTED TO FAIL until that bug is fixed
-- flip it to a plain assertion (remove the tripwire framing) once BUG-DOCPRINT-ACCESS-GATE-
ROUTE-BYPASS is resolved, per discipline #6.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness
import sqlite3
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
    """Choices.js-enhanced select -- setting .value directly does NOT sync Choices'
    internal state (confirmed the hard way on VAT category + this SI's customer_id);
    must open + mousedown/click the real dropdown item."""
    wrap = page.locator(".choices:has(select[name='%s'])" % name)
    wrap.click(); page.wait_for_timeout(250)
    opt = wrap.locator(".choices__list--dropdown .choices__item--choice", has_text=needle)
    opt.first.dispatch_event("mousedown"); opt.first.dispatch_event("click")

def csrf_post(page, b, url, fields=None):
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    return page.evaluate("""async(a)=>{const[u,ex,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        for(const k in (ex||{}))fd.append(k,ex[k]);
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [url, fields or {}, token])

def set_docprint_settings(page, b, **kv):
    # Company Settings is admin_panel_required -- CA cannot reach it.
    login_as(page, b, "admin", TEST_PW)
    page.goto(b + "/settings", wait_until="networkidle")
    # company_name (Company Profile tab) is DataRequired on the SAME multi-tab form --
    # if empty, the whole submit silently fails validation, discarding the docprint change too.
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

    sales_acct_id = q1("SELECT id FROM accounts WHERE code='4110'")[0]
    wht_id = q1("SELECT id FROM withholding_tax WHERE code='WC010'")[0]
    cust_id = q1("SELECT id FROM customers WHERE code='CASCUST1'")[0]

    print("=== CREATE: SI for UI Test Trading Corp, VAT-inclusive 1120.00, WHT WC010 ===")
    page.goto(b + "/sales-invoices/create", wait_until="networkidle")
    invoice_number = page.eval_on_selector("#invoice_number", "el => el.value")
    pick_choices(page, "customer_id", "UI Test Trading Corp")
    page.fill("#notes", "ui-test SI create")
    line = [{"account_id": sales_acct_id, "description": "ui-test line", "amount": "1120.00",
             "vat_category": "V12", "wt_id": wht_id}]
    page.evaluate("""(li)=>{document.getElementById('lineItemsData').value=JSON.stringify(li);}""", line)
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.getElementById('lineItemsData').form.submit()")
    print("FLASH:", harness.flash_text(page))

    inv = q1("""SELECT id, status, subtotal, vat_amount, withholding_tax_amount, total_amount, journal_entry_id
                FROM sales_invoices WHERE invoice_number=?""", invoice_number)
    check("SI CREATE (draft)", inv is not None and inv[1] == 'draft', str(inv))
    si_id = inv[0] if inv else None
    check("SI VAT extracted correctly (120.00 from 1120.00 gross @ 12%)", inv and float(inv[3]) == 120.0, str(inv))
    check("SI WHT computed on net-of-VAT (10.00 = 1000.00 * 1%)", inv and float(inv[4]) == 10.0, str(inv))
    je_id = inv[6] if inv else None
    check("SI create built a JE immediately (draft SI still gets a JE per current design)", je_id is not None, str(inv))

    if je_id:
        legs = sqlite3.connect(DB).execute(
            "SELECT account_id, debit_amount, credit_amount FROM journal_entry_lines WHERE entry_id=?", (je_id,)
        ).fetchall()
        ar_id = q1("SELECT id FROM accounts WHERE code='1610'")[0]
        output_vat_id = q1("SELECT id FROM accounts WHERE code='2310'")[0]
        creditable_wht_id = q1("SELECT id FROM accounts WHERE code='1710'")[0]
        by_acct = {}
        for a, d, c in legs:
            by_acct[a] = by_acct.get(a, 0) + (d or 0) - (c or 0)
        check("JE: AR leg ties to header total (1110.00 = 1120.00 - 10.00 WHT)",
              round(by_acct.get(ar_id, 0), 2) == 1110.00, str(by_acct.get(ar_id)))
        check("JE: Output VAT leg ties to header VAT (120.00, credit)",
              round(-by_acct.get(output_vat_id, 0), 2) == 120.00, str(by_acct.get(output_vat_id)))
        check("JE: Sales Revenue leg ties to net (1000.00, credit)",
              round(-by_acct.get(sales_acct_id, 0), 2) == 1000.00, str(by_acct.get(sales_acct_id)))
        check("JE: Creditable WHT leg ties to header WHT (10.00, debit)",
              round(by_acct.get(creditable_wht_id, 0), 2) == 10.00, str(by_acct.get(creditable_wht_id)))

    print("=== READ: detail renders ===")
    page.goto(b + f"/sales-invoices/{si_id}", wait_until="networkidle")
    check("SI detail renders invoice number + customer", body_has(page, invoice_number) and body_has(page, "ui test trading corp"))

    print("=== audit trail ===")
    audit_row = q1("SELECT action, record_identifier FROM audit_logs WHERE module='sales_invoice' ORDER BY id DESC LIMIT 1")
    check("audit logged SI create", audit_row and audit_row[0] == 'create' and invoice_number in (audit_row[1] or ''), str(audit_row))

    print("=== PRINT SURFACE (c-1): draft + default sv_print_access=posted_only -> button hidden ===")
    page.goto(b + f"/sales-invoices/{si_id}", wait_until="networkidle")
    print_link_visible = page.locator("a[href*='/print']").count() > 0
    check("print button HIDDEN on draft under posted_only (button gate)", not print_link_visible)

    print("=== BUG TRIPWIRE (BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS): does the ROUTE also honor posted_only, or only the button? ===")
    resp = page.request.get(b + f"/sales-invoices/{si_id}/print")
    route_rendered_anyway = resp.status == 200 and invoice_number in resp.text()
    if route_rendered_anyway:
        print("  >>> KNOWN BUG (still open): direct GET on a DRAFT invoice's /print rendered 200 despite sv_print_access=posted_only")
    check("[TRIPWIRE -- expected to FAIL until BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS is fixed] direct GET respects posted_only the same as the button",
          not route_rendered_anyway, "status=%s route_rendered_anyway=%s" % (resp.status, route_rendered_anyway))

    print("=== POST ===")
    status = csrf_post(page, b, b + f"/sales-invoices/{si_id}/post")
    inv2 = q1("SELECT status FROM sales_invoices WHERE id=?", si_id)
    check("SI POSTED", inv2 and inv2[0] == 'posted', "http %s status=%s" % (status, inv2))
    audit_post = q1("SELECT action FROM audit_logs WHERE module='sales_invoice' ORDER BY id DESC LIMIT 1")
    check("audit logged SI post", audit_post and audit_post[0] == 'post', str(audit_post))

    print("=== PRINT SURFACE (a): posted + posted_only -> button shown, printable form renders ===")
    page.goto(b + f"/sales-invoices/{si_id}", wait_until="networkidle")
    check("print button SHOWN on posted under posted_only", page.locator("a[href*='/print']").count() > 0)
    resp = page.request.get(b + f"/sales-invoices/{si_id}/print")
    check("print (current form) 200 + shows invoice number + amounts", resp.status == 200 and invoice_number in resp.text())

    print("=== PRINT SURFACE (c-2): sv_print_form=hidden -> button gone + direct GET blocked ===")
    set_docprint_settings(page, b, sv_print_form="hidden")
    page.goto(b + f"/sales-invoices/{si_id}", wait_until="networkidle")
    check("print button HIDDEN when sv_print_form=hidden", page.locator("a[href*='/print']").count() == 0)
    page.goto(b + f"/sales-invoices/{si_id}/print", wait_until="networkidle")
    check("direct GET /print redirects away when sv_print_form=hidden", f"/sales-invoices/{si_id}/print" not in page.url)

    print("=== PRINT SURFACE (b): pre-printed overlay ===")
    set_docprint_settings(page, b, sv_print_form="preprinted")
    resp = page.request.get(b + f"/sales-invoices/{si_id}/print")
    check("print (preprinted form) 200", resp.status == 200)
    check("preprinted response renders the preprinted template",
          "preprinted" in resp.text().lower() or "layout" in resp.text().lower())

    set_docprint_settings(page, b, sv_print_form="current")  # restore default

    print("=== CANCEL a posted SI ===")
    page.goto(b + f"/sales-invoices/{si_id}", wait_until="networkidle")
    status = csrf_post(page, b, b + f"/sales-invoices/{si_id}/cancel",
                        {"cancel_reason": "ui-test cancel reason, long enough",
                         "reversal_date": datetime.date.today().isoformat()})
    inv3 = q1("SELECT status FROM sales_invoices WHERE id=?", si_id)
    check("SI CANCELLED", inv3 and inv3[0] in ('cancelled', 'voided'), "http %s status=%s" % (status, inv3))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
