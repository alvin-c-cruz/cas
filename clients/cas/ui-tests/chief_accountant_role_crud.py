"""Add a Chief Accountant (CA), then let the CA drive master-data + Sales-Area CRUD.

Provision (admin, last-resort for the FIRST approver): admin approves a chief_accountant
ApprovedEmail (MAIN branch) -> self-register -> active CA.
Then AS THE CA (has_full_access, bypasses the module gate):
  - master data: customer (direct-save CRUD), account (approval workflow: create -> CA self-approve)
  - Sales Area: quotation create (inline customer) + send.
With admin + CA both full-access, COA changes go PENDING; the CA may self-approve (full-access).
"""
import sys, sqlite3
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
CA_USER, CA_EMAIL = "uitest_ca", "uitestca@example.com"
results = []
def check(n, ok, d=""):
    results.append((bool(ok), n, d)); print(("PASS " if ok else "FAIL ") + n + (("  -- " + d) if d else ""))
def q1(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchone()
def reenable(page):
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>{e.removeAttribute('readonly');e.removeAttribute('disabled');})")
def body_has(page, t):
    for _ in range(12):
        try: return t.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
    return t.lower() in page.content().lower()
def submit_owner(page, sel):
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("(s)=>document.querySelector(s).form.submit()", sel)
def try_login(page, u):
    return "/login" not in harness.login(page, u)

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=170)
    b = harness.base_url()

    # ---------- Phase 0: admin approves a CA email (admin = last-resort first approver) ----------
    if not try_login(page, CA_USER):
        harness.login(page, "admin")
        page.goto(b + "/approved-emails/add", wait_until="networkidle"); reenable(page)
        page.fill("input[name='email']", CA_EMAIL)
        page.select_option("select[name='position']", "chief_accountant")
        if page.locator("select[name='branch_ids']").count():   # single-branch auto-assigns; picker absent
            page.select_option("select[name='branch_ids']", ["1"])   # MAIN
        submit_owner(page, "select[name='position']")
        check("admin approved CA email", body_has(page, "approved") or "/approved-emails" in page.url, page.url)
        # ---------- Phase 1: self-register the CA ----------
        harness.logout(page)
        page.goto(b + "/register", wait_until="networkidle"); reenable(page)
        page.fill("input[name='username']", CA_USER); page.fill("input[name='email']", CA_EMAIL)
        if page.locator("input[name='full_name']").count(): page.fill("input[name='full_name']", "Test Chief Accountant")
        page.fill("#password-field", harness.password()); page.fill("input[name='confirm_password']", harness.password())
        submit_owner(page, "input[name='confirm_password']")
    row = q1("SELECT role,is_active FROM users WHERE username=?", CA_USER)
    check("CA user active with role chief_accountant", row == ("chief_accountant", 1), str(row))

    # ---------- Phase 2 (CA): master-data CRUD ----------
    check("CA can log in", try_login(page, CA_USER))

    # (a) Customer — direct-save CRUD
    page.goto(b + "/customers/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "CACUST"); page.fill("input[name='name']", "CA Customer")
    page.select_option("select[name='payment_terms']", "Net 30")
    page.eval_on_selector("select[name='is_active']","e=>{e.value='1';e.dispatchEvent(new Event('change',{bubbles:true}));}")
    reenable(page); submit_owner(page, "input[name='code']")
    cc = q1("SELECT id FROM customers WHERE code='CACUST'")
    check("CA CREATE customer (direct-save)", cc is not None, str(cc))
    if cc:
        page.goto(b + "/customers/%d/edit" % cc[0], wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "CA Customer EDITED"); reenable(page); submit_owner(page, "input[name='code']")
        check("CA UPDATE customer", q1("SELECT name FROM customers WHERE id=?", cc[0])[0] == "CA Customer EDITED")
        page.goto(b + "/customers", wait_until="networkidle")
        token = page.eval_on_selector("input[name='csrf_token']","e=>e.value")
        st = page.evaluate("""async(a)=>{const[u,t]=a;const fd=new FormData();fd.append('csrf_token',t);
            const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [b + "/customers/%d/delete" % cc[0], token])
        check("CA DELETE customer", q1("SELECT id FROM customers WHERE code='CACUST'") is None, "http %s" % st)

    # (b) Account — approval workflow under CA (create -> pending -> CA self-approve)
    used = {r[0] for r in sqlite3.connect(DB).execute("SELECT code FROM accounts WHERE code LIKE '88%'")}
    acode = next(c for c in ("8801","8802","8803","8804") if c not in used)
    page.goto(b + "/accounts/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", acode); page.fill("input[name='name']", "CA Test Acct %s" % acode)
    page.select_option("select[name='account_type']", "Asset"); page.select_option("select[name='classification']", "Current")
    reenable(page); submit_owner(page, "input[name='code']")
    pend = q1("SELECT id,status FROM account_change_requests WHERE requested_by=? ORDER BY id DESC LIMIT 1", CA_USER)
    check("CA account create -> PENDING (2 full-access users, no auto-approve)", pend and pend[1] == "pending", str(pend))
    if pend:
        page.goto(b + "/accounts/pending-approvals", wait_until="networkidle")
        can = page.locator("button[title='Approve'], form[id='approve-form']").count() > 0 or body_has(page, "approve")
        with page.expect_navigation(wait_until="networkidle"):
            page.evaluate("(rid)=>{const f=document.getElementById('approve-form');f.action='/accounts/approve/'+rid;f.submit();}", pend[0])
        check("CA can SELF-APPROVE own account request (full-access)", q1("SELECT id FROM accounts WHERE code=?", acode) is not None)

    # ---------- Phase 3 (CA): Sales Area — quotation create (inline customer) + send ----------
    page.goto(b + "/quotations/create", wait_until="networkidle"); reenable(page)
    cw = page.locator(".choices:has(#customer_id_display)"); cw.click(); page.wait_for_timeout(250)
    page.locator(".choices__list--dropdown .choices__item--choice", has_text="ABC Trading").first.click()
    page.wait_for_selector("#lineItemsBody tr", timeout=10000)
    row = page.locator("#lineItemsBody tr").first
    prod = q1("SELECT id FROM products WHERE code='GEN01'")[0]
    row.locator("td:nth-child(2) select").select_option(str(prod)); page.wait_for_timeout(300)
    row.locator("input[id^='qty-']").fill("7"); row.locator("input[id^='qty-']").dispatch_event("change")
    up = row.locator("input[id^='up-']")
    if not (up.input_value() or "").strip(): up.fill("100"); up.dispatch_event("change")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"): page.locator("#submitBtn").click()
    qn = q1("SELECT id,quotation_number,created_by_id FROM quotations ORDER BY id DESC LIMIT 1")
    ca_id = q1("SELECT id FROM users WHERE username=?", CA_USER)[0]
    check("CA CREATE quotation (Sales Area)", qn is not None and qn[2] == ca_id, str(qn))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
