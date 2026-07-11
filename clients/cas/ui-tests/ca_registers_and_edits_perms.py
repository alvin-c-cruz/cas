"""CA as approver + permission editor.

Q1: can the CA REGISTER accountants and staff?  -> CA approves their emails (full-access =
    immediate approval) -> they self-register -> active with the CA-granted role.
Q2: can the CA EDIT their permissions after registration?
    - STAFF/viewer: YES (Staff Management admits CA; is_in_scope allows staff/viewer).
    - ACCOUNTANT: NO (out of Staff-Management scope; edit_user is admin-only) -> known gap.
"""
import sys, sqlite3
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
CA = "uitest_ca"
NEW = [("uitest_ca_acct", "caacct@example.com", "accountant"),
       ("uitest_ca_staff", "castaff@example.com", "staff")]
results = []
def check(n, ok, d=""):
    results.append((bool(ok), n, d)); print(("PASS " if ok else "FAIL ") + n + (("  -- " + d) if d else ""))
def q1(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchone()
def reenable(page): page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>{e.removeAttribute('readonly');e.removeAttribute('disabled');})")
def body_has(page, t):
    for _ in range(12):
        try: return t.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
    return t.lower() in page.content().lower()
def submit_owner(page, sel):
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("(s)=>document.querySelector(s).form.submit()", sel)
def try_login(page, u): return "/login" not in harness.login(page, u)
def perms(username):
    r = q1("SELECT book_permissions FROM users WHERE username=?", username)
    import json;
    try: return json.loads(r[0]) if r and r[0] else {}
    except Exception: return {}

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=160)
    b = harness.base_url()
    ca_id = q1("SELECT id FROM users WHERE username=?", CA)[0]

    # ================= Q1: CA registers accountant + staff =================
    harness.login(page, CA)
    for uname, email, pos in NEW:
        if q1("SELECT id FROM users WHERE username=?", uname):
            continue
        page.goto(b + "/approved-emails/add", wait_until="networkidle"); reenable(page)
        page.fill("input[name='email']", email)
        page.select_option("select[name='position']", pos)
        if page.locator("select[name='branch_ids']").count():
            page.select_option("select[name='branch_ids']", ["1"])
        submit_owner(page, "select[name='position']")
        # CA is full-access -> email immediately approved, with CA as approver
        appr = q1("SELECT status, approved_by_user_id FROM approved_emails WHERE email=?", email)
        check("CA approved %s email (immediate, CA=approver)" % pos,
              appr and appr[0] == "approved" and appr[1] == ca_id, str(appr))
        harness.logout(page)
        page.goto(b + "/register", wait_until="networkidle"); reenable(page)
        page.fill("input[name='username']", uname); page.fill("input[name='email']", email)
        if page.locator("input[name='full_name']").count(): page.fill("input[name='full_name']", uname)
        page.fill("#password-field", harness.password()); page.fill("input[name='confirm_password']", harness.password())
        submit_owner(page, "input[name='confirm_password']")
        harness.login(page, CA)
    for uname, email, pos in NEW:
        check("registered %s active with role=%s" % (uname, pos),
              q1("SELECT role,is_active FROM users WHERE username=?", uname) == (pos, 1))

    staff_id = q1("SELECT id FROM users WHERE username='uitest_ca_staff'")[0]
    acct_id  = q1("SELECT id FROM users WHERE username='uitest_ca_acct'")[0]

    # ================= Q2a: CA edits the STAFF user's perms (allowed) =================
    harness.login(page, CA)
    page.goto(b + "/staff-management", wait_until="networkidle")
    check("Staff Mgmt lists the staff user (in CA scope)", body_has(page, "uitest_ca_staff"))
    check("Staff Mgmt does NOT list the accountant (out of scope)", not body_has(page, "uitest_ca_acct"))

    before = perms("uitest_ca_staff")
    page.goto(b + "/staff-management/%d/edit" % staff_id, wait_until="networkidle")
    on_editor = "/edit" in page.url and page.locator("input[name^='book_']").count() > 0
    check("CA can OPEN the staff permission editor", on_editor, "url=%s" % page.url)
    if on_editor:
        reenable(page)
        vend = page.locator("input[name='book_vendors']")     # non-optional module, in the grid
        if vend.count(): vend.first.check()
        submit_owner(page, "input[name^='book_'], select[name='role']")
        after = perms("uitest_ca_staff")
        check("CA GRANTED 'vendors' to staff (persisted)", after.get("vendors") is True,
              "before=%s after_vendors=%s" % (bool(before.get("vendors")), after.get("vendors")))

    # ================= Q2b: CA CANNOT edit the ACCOUNTANT's perms (known gap) =================
    resp = page.goto(b + "/staff-management/%d/edit" % acct_id, wait_until="networkidle")
    st = resp.status if resp else 0
    blocked_sm = st == 403 or body_has(page, "forbidden") or "/staff-management/%d/edit" % acct_id not in page.url
    check("CA blocked from editing ACCOUNTANT via Staff Mgmt (out of scope / 403)", blocked_sm, "http %s url=%s" % (st, page.url))
    page.goto(b + "/users/%d/edit" % acct_id, wait_until="networkidle")
    blocked_eu = "dashboard" in page.url or body_has(page, "do not have") or body_has(page, "permission") or ("/users/%d/edit" % acct_id) not in page.url
    check("CA blocked from editor_user (admin-only) for the accountant (KNOWN GAP: no non-admin path)", blocked_eu, "url=%s" % page.url)

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
