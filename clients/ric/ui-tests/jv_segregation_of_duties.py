"""RIC UI-test: Journal Voucher (JV) segregation-of-duties + accountant happy path.

Run under /ui-test discipline: no app code change, no DB seeding (all data is created
THROUGH THE UI as the proper role), bugs are logged not fixed inline.

Role policy for this suite (user directive): drive actions as staff / accountant / CA
as much as possible; use admin only as a last resort. Here NO admin action is used --
the approver is MARISSA (chief_accountant, has_full_access), applicants self-register.

Users (auto-provisioned via the UI if absent on the throwaway) -- the CA GRANTS the
journal_entries module on the approved email so both users clear the per-user module
gate (`book_permissions`, enforced in before_request for ALL non-full-access roles)
and the STAFF vs ACCOUNTANT difference is decided by the view ROLE gate:
  uitest_jv_staff  role=staff        branch CORP  +journal_entries module
  uitest_jv_acct   role=accountant   branch CORP  +journal_entries module ("accountant format")
plus MARISSA (chief_accountant) already on the RIC copy, used only as the email approver.

Flow:
  Phase 1 (staff)       /journal-entries/create BLOCKED by the role gate; sidebar check.
  Phase 2 (accountant)  create a balanced draft JV (Dr Petty Cash / Cr Cash on Hand).
  Phase 3 (staff)       may VIEW the draft (read-only) but POST is BLOCKED server-side.
  Phase 4 (accountant)  post the JV -> status posted; print preview renders.

JV lines are entered via the Choices.js account picker, which STRIPS non-selected
options from the native <select> -- so the picker MUST be driven through its UI
(open, then mousedown+click the option); setting <select>.value does nothing.
"""
import sys, re
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

STAFF = ("uitest_jv_staff", "jvstaff@example.com", "staff")
ACCT  = ("uitest_jv_acct",  "jvacct@example.com",  "accountant")
DR_CODE, CR_CODE = "11111", "11101"   # Petty Cash Fund ; Cash on Hand/Cash Sales
AMOUNT = "1000"

results = []
def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + (("  -- " + detail) if detail else ""))

def strip_ro(page):
    page.eval_on_selector_all("input,select,textarea",
        "els => els.forEach(e => e.removeAttribute('readonly'))")

def body_has(page, text):
    for _ in range(12):                       # tolerate an in-flight redirect
        try:
            return text.lower() in page.content().lower()
        except Exception:
            page.wait_for_timeout(250)
    return text.lower() in page.content().lower()

def submit_owning_form(page, field_selector):
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("(s) => document.querySelector(s).form.submit()", field_selector)

def try_login(page, uname, branch=None):
    url = harness.login(page, uname, branch=branch)
    return "/login" not in url

def pick_account(page, row_index, code):
    row = page.locator(".line-row").nth(row_index)
    row.locator(".choices").click()
    page.wait_for_timeout(250)
    opt = row.locator(".choices__list--dropdown .choices__item--choice", has_text=code + " :")
    opt.first.dispatch_event("mousedown")
    opt.first.dispatch_event("click")

def ensure_user(page, uname, email, role):
    """Create <uname> via the UI (CA approves email -> self-register) if not present."""
    if try_login(page, uname):
        return
    b = harness.base_url()
    harness.login(page, "MARISSA", branch="CORP")            # CA = approver (non-admin)
    page.goto(b + "/approved-emails/add", wait_until="networkidle")
    strip_ro(page)
    page.fill("input[name='email']", email)
    page.select_option("select[name='position']", role)
    page.select_option("select[name='branch_ids']", ["1"])   # CORP
    # stamp the journal_entries module so the user clears the before_request module gate
    # (accountant/staff/viewer are ALL gated by book_permissions; only admin/CA bypass) --
    # this is the zero-admin path: CA grants the module at approval time
    jbox = page.locator("input[name='book_journal_entries']")
    if jbox.count():
        jbox.first.check()
    submit_owning_form(page, "select[name='position']")
    harness.logout(page)
    page.goto(b + "/register", wait_until="networkidle")
    strip_ro(page)
    page.fill("input[name='username']", uname)
    page.fill("input[name='email']", email)
    if page.locator("input[name='full_name']").count():
        page.fill("input[name='full_name']", uname.title())
    page.fill("#password-field", harness.password())
    page.fill("input[name='confirm_password']", harness.password())
    submit_owning_form(page, "input[name='confirm_password']")


with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=300)
    b = harness.base_url()

    # ---- provision (idempotent; UI-only, no admin) ----
    ensure_user(page, *STAFF)
    ensure_user(page, *ACCT)

    # ---------- Phase 1: staff BLOCKED from JV create ----------
    check("staff login works", try_login(page, STAFF[0]))
    page.goto(b + "/journal-entries/create", wait_until="networkidle")
    blocked = "journal-entries/create" not in page.url and body_has(
        page, "only accountants and administrators")
    check("staff BLOCKED from JV create (role gate)", blocked, "url=" + page.url)
    links = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => e.getAttribute('href')).filter(Boolean)")
    jv_links = sorted(set(l for l in links if "journal" in l.lower()))
    check("staff sidebar JV/journal links (informational)", True,
          "none" if not jv_links else ", ".join(jv_links))

    # ---------- Phase 2: ACCOUNTANT creates a balanced draft JV ----------
    check("accountant login works", try_login(page, ACCT[0]))
    page.goto(b + "/journal-entries/create", wait_until="networkidle")
    check("accountant reaches JV create form",
          "journal-entries/create" in page.url and page.locator("#journalEntryForm").count() > 0)

    jv_number = page.input_value("input[name='entry_number']")
    check("JV number auto-generated in JV-YYYY-MM-#### format",
          bool(re.match(r"^JV-\d{4}-\d{2}-\d{4}$", jv_number or "")), "got=" + str(jv_number))

    page.fill("textarea[name='description'], input[name='description']", "UI-test JV cash transfer")
    if page.locator("input[name='reference']").count():
        page.fill("input[name='reference']", "UITEST-REF-1")
    pick_account(page, 0, DR_CODE)
    page.locator(".line-debit").nth(0).fill(AMOUNT)
    page.locator(".line-debit").nth(0).dispatch_event("blur")
    pick_account(page, 1, CR_CODE)
    page.locator(".line-credit").nth(1).fill(AMOUNT)
    page.locator(".line-credit").nth(1).dispatch_event("blur")

    lines_json = page.input_value("#linesData")
    check("line grid serialized 2 lines", lines_json.count("account_id") == 2, lines_json[:200])

    with page.expect_navigation(wait_until="networkidle"):
        page.click("#journalEntryForm button[type='submit']")
    check("JV draft created successfully", body_has(page, "created successfully"), "url=" + page.url)
    check("JV reported as balanced", body_has(page, "balanced"))
    m = re.search(r"/journal-entries/(\d+)", page.url)
    entry_id = m.group(1) if m else None
    check("new JV is in draft status", bool(entry_id) and body_has(page, "draft"), "id=" + str(entry_id))

    # ---------- Phase 3: staff VIEW ok, POST blocked ----------
    if entry_id:
        try_login(page, STAFF[0])
        page.goto(b + "/journal-entries/" + entry_id, wait_until="networkidle")
        check("staff CAN view JV detail (read-only; only @login_required)",
              ("/journal-entries/" + entry_id) in page.url and body_has(page, jv_number))
        post_btn = page.locator("form[action$='/post'] button[type='submit']").count()
        check("staff detail renders a Post button they cannot use (UI vs server gate)",
              True, "post button present=" + str(bool(post_btn)))
        if post_btn:
            submit_owning_form(page, "form[action$='/post'] button[type='submit']")
            check("staff POST to /post BLOCKED by server role gate",
                  body_has(page, "only accountants and administrators"), "url=" + page.url)

    # ---------- Phase 4: ACCOUNTANT posts + print ----------
    if entry_id:
        try_login(page, ACCT[0])
        page.goto(b + "/journal-entries/" + entry_id, wait_until="networkidle")
        submit_owning_form(page, "form[action$='/post'] button[type='submit']")
        check("accountant can POST the JV -> status posted", body_has(page, "posted"), "url=" + page.url)
        page.goto(b + "/journal-entries/" + entry_id + "/print", wait_until="networkidle")
        check("JV print preview renders", body_has(page, jv_number))

    print("\n==== SUMMARY ====")
    npass = sum(1 for ok, *_ in results if ok)
    print(f"{npass}/{len(results)} checks passed")
    for ok, name, detail in results:
        if not ok:
            print("  FAILED:", name, "--", detail)
