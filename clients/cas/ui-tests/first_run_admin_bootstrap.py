"""CAS regression spec: first-run admin bootstrap (BUG-NO-FIRSTRUN-ADMIN-BOOTSTRAP).

Graduated from the bug-tracker (FIXED on main 2026-07-11) per /ui-test discipline #6.
Browser-only end-to-end guard for the empty-DB bootstrap that pytest can't fully drive:

  1. On an admin-less DB, registering the EXACT username `admin` bypasses the empty
     ApprovedEmail whitelist -> active admin + auto-created MAIN branch -> can log in and
     lands on a working dashboard (branch gate auto-selects the lone branch).
  2. The bypass CLOSES once an admin exists: a second non-whitelisted registration is
     rejected by the whitelist ("not pre-approved") and is NOT granted admin.

Run against a FRESH `/ui-test cas` (empty schema, zero rows). It intentionally builds
state (creates the admin) -- run it first, then continue driving as `admin`.
"""
import sys, sqlite3
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

ADMIN_PW = harness.password()          # shared test pw; satisfies the >=12 policy
DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"

results = []
def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + (("  -- " + detail) if detail else ""))

def strip_ro(page):
    page.eval_on_selector_all("input,select,textarea",
        "els => els.forEach(e => e.removeAttribute('readonly'))")

def body_has(page, text):
    for _ in range(12):
        try: return text.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
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

def db1(sql):
    return sqlite3.connect(DB).execute(sql).fetchone()

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=300)
    b = harness.base_url()

    # precondition: empty DB, no admin
    check("precondition: DB starts with zero users", db1("SELECT COUNT(*) FROM users")[0] == 0)

    # --- 1. first-run bootstrap: register `admin` ---
    register(page, b, "admin", "admin@example.com", ADMIN_PW)
    check("registering `admin` is NOT rejected by the empty whitelist (bootstrap)",
          not body_has(page, "not pre-approved"), "url=" + page.url)
    row = db1("SELECT role, is_active FROM users WHERE username='admin'")
    check("admin user created active with role=admin", row == ("admin", 1), "row=" + str(row))
    br = db1("SELECT code, name FROM branches")
    check("default MAIN branch auto-created", br is not None and br[0] == "MAIN", "branch=" + str(br))
    link = db1("SELECT COUNT(*) FROM user_branches ub JOIN users u ON u.id=ub.user_id WHERE u.username='admin'")
    check("MAIN branch assigned to admin", link[0] == 1)

    # log in as admin -> should land on a working dashboard (lone branch auto-selected)
    landing = harness.login(page, "admin")
    check("admin can log in and reach the dashboard (not stuck at login/branch)",
          "/login" not in landing and "select-branch" not in landing, "landing=" + landing)

    # --- 2. bypass CLOSES once an admin exists ---
    harness.logout(page)
    register(page, b, "staff2", "staff2@example.com", ADMIN_PW)
    check("2nd non-whitelisted registration REJECTED (bypass closed)",
          body_has(page, "not pre-approved"), "url=" + page.url)
    check("no extra admin minted; staff2 not created", db1("SELECT COUNT(*) FROM users WHERE role='admin'")[0] == 1
          and db1("SELECT COUNT(*) FROM users WHERE username='staff2'")[0] == 0)

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, name, detail in results:
        if not ok: print("  FAILED:", name, "--", detail)
