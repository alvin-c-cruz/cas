"""Accountant role vs Sales Area: the MIDDLE tier -- module-gated like staff, but an
APPROVER like CA. Provision an accountant granted only the Sales-chain modules, then verify:
  * MODULE GATE enforced (like staff): non-granted modules blocked.
  * APPROVE ALLOWED (unlike staff): accept a Quotation, approve+deliver a DR.
Contrast: staff is blocked from approve; accountant is not (gate = has_full_access or accountant).
"""
import sys, sqlite3
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
ACCT, EMAIL = "uitest_acct", "uitestacct2@example.com"
GRANT = ["quotations", "sales_orders", "delivery_receipts", "customers", "products"]
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

_TOK = {"v": None}
def post(page, b, url, fields=None):
    if _TOK["v"] is None:
        page.goto(b + "/quotations/create", wait_until="networkidle")
        _TOK["v"] = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    return page.evaluate("""async(a)=>{const[u,ex,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        for(const k in (ex||{}))fd.append(k,ex[k]);const r=await fetch(u,{method:'POST',body:fd});return r.status;}""",
        [url, fields or {}, _TOK["v"]])

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=160)
    b = harness.base_url()
    prod = q1("SELECT id FROM products WHERE code='GEN01'")[0]

    # ---------- provision accountant (admin approves, stamps Sales-chain perms) ----------
    if not try_login(page, ACCT):
        harness.login(page, "admin")
        page.goto(b + "/approved-emails/add", wait_until="networkidle"); reenable(page)
        page.fill("input[name='email']", EMAIL)
        page.select_option("select[name='position']", "accountant")
        if page.locator("select[name='branch_ids']").count():
            page.select_option("select[name='branch_ids']", ["1"])
        for k in GRANT:
            box = page.locator("input[name='book_%s']" % k)
            if box.count(): box.first.check()
        submit_owner(page, "select[name='position']")
        harness.logout(page)
        page.goto(b + "/register", wait_until="networkidle"); reenable(page)
        page.fill("input[name='username']", ACCT); page.fill("input[name='email']", EMAIL)
        if page.locator("input[name='full_name']").count(): page.fill("input[name='full_name']", "Sales Accountant")
        page.fill("#password-field", harness.password()); page.fill("input[name='confirm_password']", harness.password())
        submit_owner(page, "input[name='confirm_password']")
    check("accountant user active (role=accountant)", q1("SELECT role,is_active FROM users WHERE username=?", ACCT) == ("accountant", 1))
    check("accountant can log in", try_login(page, ACCT))

    # ---------- MODULE GATE enforced (like staff) ----------
    def blocked(path):
        page.goto(b + path, wait_until="networkidle")
        return "dashboard" in page.url or body_has(page, "do not have access to this module")
    check("module gate enforced: /vendors blocked", blocked("/vendors"))
    check("module gate enforced: /accounts-payable blocked", blocked("/accounts-payable"))
    page.goto(b + "/quotations", wait_until="networkidle")
    check("granted module reachable: /quotations", "quotations" in page.url and not body_has(page, "do not have access"))

    # ---------- APPROVER ALLOWED (unlike staff): accept a quote, approve+deliver a DR ----------
    # accountant creates + sends + ACCEPTS a quotation (accept = approver action)
    page.goto(b + "/quotations/create", wait_until="networkidle"); reenable(page)
    page.locator(".choices:has(#customer_id_display)").click(); page.wait_for_timeout(250)
    page.locator(".choices__list--dropdown .choices__item--choice", has_text="ABC Trading").first.click()
    page.wait_for_selector("#lineItemsBody tr", timeout=10000)
    r = page.locator("#lineItemsBody tr").first
    r.locator("td:nth-child(2) select").select_option(str(prod)); page.wait_for_timeout(300)
    r.locator("input[id^='qty-']").fill("6"); r.locator("input[id^='qty-']").dispatch_event("change")
    up = r.locator("input[id^='up-']")
    if not (up.input_value() or "").strip(): up.fill("100"); up.dispatch_event("change")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"): page.locator("#submitBtn").click()
    qid = q1("SELECT id FROM quotations ORDER BY id DESC LIMIT 1")[0]
    post(page, b, "%s/quotations/%d/send" % (b, qid))
    post(page, b, "%s/quotations/%d/accept" % (b, qid))
    check("APPROVER ok: accountant ACCEPTED a Quotation (sent->accepted)",
          q1("SELECT status FROM quotations WHERE id=?", qid)[0] == "accepted",
          q1("SELECT status FROM quotations WHERE id=?", qid)[0])
    so_id = q1("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")[0]
    post(page, b, "%s/sales-orders/%d/confirm" % (b, so_id))
    # DR against SO -> approve + deliver (approver actions)
    page.goto(b + "/delivery-receipts/create?so=%d" % so_id, wait_until="networkidle"); reenable(page)
    page.evaluate("""(s)=>{const el=document.querySelector("select[name='sales_order_id']");if(el){el.value=String(s);el.dispatchEvent(new Event('change',{bubbles:true}));}}""", so_id)
    page.wait_for_selector(".qty-input", timeout=8000)
    page.evaluate("""()=>{const i=document.querySelector('.qty-input');i.value=(i.getAttribute('max')||'6');i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));}""")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"): page.evaluate("()=>document.querySelector('form').submit()")
    dr_id = q1("SELECT id FROM delivery_receipts ORDER BY id DESC LIMIT 1")[0]
    post(page, b, "%s/delivery-receipts/%d/approve" % (b, dr_id))
    check("APPROVER ok: accountant APPROVED a DR (unlike staff)", q1("SELECT status FROM delivery_receipts WHERE id=?", dr_id)[0] == "approved",
          q1("SELECT status FROM delivery_receipts WHERE id=?", dr_id)[0])
    post(page, b, "%s/delivery-receipts/%d/deliver" % (b, dr_id))
    check("APPROVER ok: accountant DELIVERED a DR", q1("SELECT status FROM delivery_receipts WHERE id=?", dr_id)[0] == "delivered")

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
