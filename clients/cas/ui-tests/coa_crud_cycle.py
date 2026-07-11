"""COA full CRUD + approval-cycle test (as admin), on a disposable 9999 account.

Exercises: Create->approve, Read(view), Update->approve, Update->REJECT (must not apply),
Delete->approve. Admin never auto-approves COA, so every mutation is create-request ->
review. Leaves the foundation COA untouched (creates then deletes 9999).
"""
import sys, sqlite3
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
results = []
def check(name, ok, detail=""):
    results.append((bool(ok), name, detail)); print(("PASS " if ok else "FAIL ") + name + (("  -- " + detail) if detail else ""))
def q1(sql, *a):
    return sqlite3.connect(DB).execute(sql, a).fetchone()
def reenable(page):
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>{e.removeAttribute('readonly');e.removeAttribute('disabled');})")
def submit_code_form(page):
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.querySelector(\"input[name='code']\").form.submit()")
def body_has(page, t):
    for _ in range(12):
        try: return t.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
    return t.lower() in page.content().lower()
def latest_pending(account_id=None, change_type=None):
    sql = "SELECT id FROM account_change_requests WHERE status='pending'"; a=[]
    if account_id is not None: sql += " AND account_id=?"; a.append(account_id)
    if change_type: sql += " AND change_type=?"; a.append(change_type)
    sql += " ORDER BY id DESC LIMIT 1"
    r = q1(sql, *a); return r[0] if r else None
def approve(page, b, rid):
    page.goto(b + "/accounts/pending-approvals", wait_until="networkidle")
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("(rid)=>{var f=document.getElementById('approve-form');f.action='/accounts/approve/'+rid;f.submit();}", rid)
def reject(page, b, rid):
    page.goto(b + "/accounts/pending-approvals", wait_until="networkidle")
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("(rid)=>{var f=document.getElementById('reject-form');f.action='/accounts/reject/'+rid;"
                      "var t=document.createElement('input');t.type='hidden';t.name='rejection_reason';t.value='crud test reject';f.appendChild(t);f.submit();}", rid)

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=200)
    b = harness.base_url()
    harness.login(page, "admin")

    # ---- CREATE ----
    page.goto(b + "/accounts/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "9999"); page.fill("input[name='name']", "CRUD Test Account")
    page.select_option("select[name='account_type']", "Asset"); page.select_option("select[name='classification']", "Current")
    reenable(page); submit_code_form(page)
    approve(page, b, latest_pending())
    acct = q1("SELECT id,name FROM accounts WHERE code='9999'")
    check("CREATE -> approve: account exists", acct is not None, str(acct))
    aid = acct[0] if acct else None

    # ---- READ ----
    if aid:
        page.goto(b + "/accounts/%d" % aid, wait_until="networkidle")
        check("READ: view renders code+name", body_has(page, "9999") and body_has(page, "CRUD Test Account"))

    # ---- UPDATE -> approve ----
    if aid:
        page.goto(b + "/accounts/%d/edit" % aid, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "CRUD Test EDITED"); page.fill("textarea[name='request_reason']", "rename via crud test")
        reenable(page); submit_code_form(page)
        approve(page, b, latest_pending(account_id=aid, change_type="update"))
        check("UPDATE -> approve: name changed", q1("SELECT name FROM accounts WHERE id=?", aid)[0] == "CRUD Test EDITED",
              q1("SELECT name FROM accounts WHERE id=?", aid)[0])

    # ---- UPDATE -> REJECT (must NOT apply) ----
    if aid:
        page.goto(b + "/accounts/%d/edit" % aid, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "SHOULD NOT APPLY"); page.fill("textarea[name='request_reason']", "reject-path test")
        reenable(page); submit_code_form(page)
        rid = latest_pending(account_id=aid, change_type="update")
        reject(page, b, rid)
        nm = q1("SELECT name FROM accounts WHERE id=?", aid)[0]
        st = q1("SELECT status FROM account_change_requests WHERE id=?", rid)[0]
        check("UPDATE -> reject: change NOT applied", nm == "CRUD Test EDITED", "name=" + nm)
        check("UPDATE -> reject: request marked rejected", st == "rejected", "status=" + st)

    # ---- DELETE -> approve ----
    if aid:
        page.goto(b + "/accounts/", wait_until="networkidle")
        with page.expect_navigation(wait_until="networkidle"):
            page.evaluate("(aid)=>{var f=document.getElementById('delete-form');f.action='/accounts/'+aid+'/delete';"
                          "document.getElementById('delete-request-reason').value='crud delete test';f.submit();}", aid)
        approve(page, b, latest_pending(account_id=aid, change_type="delete"))
        check("DELETE -> approve: account removed", q1("SELECT id FROM accounts WHERE code='9999'") is None)

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, name, d in results:
        if not ok: print("  FAILED:", name, "--", d)
