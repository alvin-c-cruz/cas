"""Journal Voucher (JV) full CRUD + posting + all 3 print surfaces (TEST-CASES.md T1.5/T1.6/T1.10).

Requires the CAS-scope shared setup (`_shared_setup_cas_scope.py`) to have run first --
uses accounts 1610 (Accounts Receivable - Trade) and 4110 (Sales Revenue) from that
setup, and logs in as `uitest_ca` (chief_accountant, has_full_access -- no
book_permissions needed for the core `journal_entries` module).

Covers: create (balanced, draft) -> read (detail renders) -> audit trail (create +
post actions logged) -> print surface (a) printable form -> print surface (c) hidden
button/blocked direct-GET when `jv_print_form=hidden` -> print surface (b) pre-printed
overlay -> post (draft->posted) -> cancel (posted->cancelled).

Note: changing `jv_print_form` goes through Company Settings (admin-only; CA can't
reach it), and that form requires `company_name` (Company Profile tab) -- if unset,
the WHOLE multi-tab settings submit silently fails validation, discarding the
docprint change too. This spec sets a minimal `company_name` if empty before saving.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness
import sqlite3

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

def pick_row_account(row, needle):
    """The JV line-item account select has no name= attribute (only data-field), so
    target the row's Choices.js wrapper directly rather than by select[name=...]."""
    wrap = row.locator(".choices")
    wrap.click(); row.page.wait_for_timeout(250)
    opt = wrap.locator(".choices__list--dropdown .choices__item--choice", has_text=needle)
    opt.first.dispatch_event("mousedown"); opt.first.dispatch_event("click")

def set_jv_print_form(page, b, value):
    # Company Settings is admin_panel_required -- CA cannot reach it.
    login_as(page, b, "admin", TEST_PW)
    page.goto(b + "/settings", wait_until="networkidle")
    # Company Profile's company_name is DataRequired on the SAME form -- ensure it's set
    # or the whole multi-tab submit silently fails validation (discarding the docprint change too).
    if not (page.eval_on_selector("#company_name", "el => el.value") or "").strip():
        page.click(".tab[data-tab-group='settings'][data-tab='profile']")
        page.wait_for_timeout(150)
        page.fill("#company_name", "UI Test Company")
    page.click(".tab[data-tab-group='settings'][data-tab='docprint']")
    page.wait_for_timeout(200)
    page.select_option("#jv_print_form", value)
    page.click("button[type=submit].btn-primary")
    page.wait_for_load_state("networkidle")
    print("  set jv_print_form=%s FLASH: %r" % (value, harness.flash_text(page)))
    login_as(page, b, "uitest_ca", TEST_PW)

TEST_PW = harness.password()

with sync_playwright() as pw:
    browser, page = harness.connect(pw)
    b = harness.base_url()
    login_as(page, b, "uitest_ca", TEST_PW)

    print("=== CREATE: balanced JV (1610 debit / 4110 credit, 1000.00) ===")
    page.goto(b + "/journal-entries/create", wait_until="networkidle")
    entry_number = page.eval_on_selector("#entry_number", "el => el.value")
    page.fill("#description", "ui-test JV create")
    page.fill("#reference", "JVTEST-REF")
    page.select_option("#entry_type", "adjustment")

    rows = page.locator("#linesTableBody tr.line-row")
    row0 = rows.nth(0)
    pick_row_account(row0, "1610 : Accounts Receivable - Trade")
    row0.locator("input.line-debit").fill("1000.00")
    row0.locator("input.line-debit").dispatch_event("change")

    row1 = rows.nth(1)
    pick_row_account(row1, "4110 : Sales Revenue")
    row1.locator("input.line-credit").fill("1000.00")
    row1.locator("input.line-credit").dispatch_event("change")

    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.getElementById('journalEntryForm').submit()")
    print("FLASH:", harness.flash_text(page))

    entry = q1("SELECT id, status, total_debit, total_credit, is_balanced FROM journal_entries WHERE entry_number=?", entry_number)
    check("JV CREATE (draft, balanced)", entry is not None and entry[1] == 'draft' and entry[4] in (1, '1', True), str(entry))
    jv_id = entry[0] if entry else None
    check("JV amounts tie (debit==credit==1000.00)", entry and float(entry[2]) == 1000.0 and float(entry[3]) == 1000.0, str(entry))

    print("=== READ: detail page renders ===")
    page.goto(b + f"/journal-entries/{jv_id}", wait_until="networkidle")
    check("JV detail renders entry number + description", body_has(page, entry_number) and body_has(page, "ui-test jv create"))

    print("=== audit trail ===")
    audit_row = q1("SELECT action, record_identifier FROM audit_logs WHERE module='journal_entry' ORDER BY id DESC LIMIT 1")
    check("audit logged JV create", audit_row and audit_row[0] == 'create' and entry_number in (audit_row[1] or ''), str(audit_row))

    print("=== PRINT SURFACE (a): printable form, default 'current' ===")
    resp = page.request.get(b + f"/journal-entries/{jv_id}/print")
    check("print (current form) 200 + shows entry number", resp.status == 200 and entry_number in resp.text())

    print("=== PRINT SURFACE (c): hidden setting -> button gone + direct GET blocked ===")
    set_jv_print_form(page, b, "hidden")
    page.goto(b + f"/journal-entries/{jv_id}", wait_until="networkidle")
    check("print button HIDDEN on detail when jv_print_form=hidden", not body_has(page, "print"))
    page.goto(b + f"/journal-entries/{jv_id}/print", wait_until="networkidle")
    check("direct GET /print redirects away when hidden", "/journal-entries/" + str(jv_id) + "/print" not in page.url)

    print("=== PRINT SURFACE (b): pre-printed overlay ===")
    set_jv_print_form(page, b, "preprinted")
    resp = page.request.get(b + f"/journal-entries/{jv_id}/print")
    check("print (preprinted form) 200", resp.status == 200)
    check("preprinted response renders the preprinted template (has layout designer markers)",
          "preprinted" in resp.text().lower() or "layout" in resp.text().lower())

    set_jv_print_form(page, b, "current")  # restore default

    print("=== POST ===")
    page.goto(b + f"/journal-entries/{jv_id}", wait_until="networkidle")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    status = page.evaluate("""async(a)=>{const[u,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [b + f"/journal-entries/{jv_id}/post", token])
    entry2 = q1("SELECT status FROM journal_entries WHERE id=?", jv_id)
    check("JV POSTED", entry2 and entry2[0] == 'posted', "http %s status=%s" % (status, entry2))

    audit_post = q1("SELECT action FROM audit_logs WHERE module='journal_entry' ORDER BY id DESC LIMIT 1")
    check("audit logged JV post", audit_post and audit_post[0] == 'post', str(audit_post))

    print("=== CANCEL a posted JV ===")
    page.goto(b + f"/journal-entries/{jv_id}", wait_until="networkidle")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    status = page.evaluate("""async(a)=>{const[u,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [b + f"/journal-entries/{jv_id}/cancel", token])
    entry3 = q1("SELECT status FROM journal_entries WHERE id=?", jv_id)
    check("JV CANCELLED", entry3 and entry3[0] == 'cancelled', "http %s status=%s" % (status, entry3))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
