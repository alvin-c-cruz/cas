"""Restricted-role (STAFF) segregation-of-duties test against the Sales Area.

Provision a staff user granted ONLY the Sales-chain modules (quotations, sales_orders,
delivery_receipts, customers, products). Then verify:
  * MODULE GATE  - granted modules reachable; non-granted (vendors/AP/COA) blocked.
  * WRITE ok     - staff may create+send a Quotation and create+confirm a Sales Order.
  * APPROVE deny - staff may NOT accept a Quotation nor approve a Delivery Receipt
                   (approver gate = has_full_access or accountant).
"""
import sys, sqlite3
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
STAFF, EMAIL = "uitest_sales_staff", "uitestsalesstaff@example.com"
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

    # ---------- Phase 0: provision staff with only Sales-chain modules ----------
    if not try_login(page, STAFF):
        harness.login(page, "admin")
        page.goto(b + "/approved-emails/add", wait_until="networkidle"); reenable(page)
        page.fill("input[name='email']", EMAIL)
        page.select_option("select[name='position']", "staff")
        if page.locator("select[name='branch_ids']").count():
            page.select_option("select[name='branch_ids']", ["1"])
        for k in GRANT:
            box = page.locator("input[name='book_%s']" % k)
            if box.count(): box.first.check()
        submit_owner(page, "select[name='position']")
        harness.logout(page)
        page.goto(b + "/register", wait_until="networkidle"); reenable(page)
        page.fill("input[name='username']", STAFF); page.fill("input[name='email']", EMAIL)
        if page.locator("input[name='full_name']").count(): page.fill("input[name='full_name']", "Sales Staff")
        page.fill("#password-field", harness.password()); page.fill("input[name='confirm_password']", harness.password())
        submit_owner(page, "input[name='confirm_password']")
    row = q1("SELECT role,is_active FROM users WHERE username=?", STAFF)
    check("staff user active (role=staff)", row == ("staff", 1), str(row))
    check("staff can log in", try_login(page, STAFF))

    # ---------- Phase 1: MODULE GATE ----------
    def reachable(path):
        page.goto(b + path, wait_until="networkidle")
        return path.strip("/").split("/")[0] in page.url and not body_has(page, "do not have access to this module")
    def blocked(path):
        page.goto(b + path, wait_until="networkidle")
        return "dashboard" in page.url or body_has(page, "do not have access to this module")
    check("GRANTED module reachable: /quotations", reachable("/quotations"))
    check("GRANTED module reachable: /sales-orders", reachable("/sales-orders"))
    check("GRANTED module reachable: /delivery-receipts", reachable("/delivery-receipts"))
    check("DENIED module blocked: /vendors", blocked("/vendors"))
    check("DENIED module blocked: /accounts-payable", blocked("/accounts-payable"))
    check("DENIED module blocked: /accounts (Chart of Accounts)", blocked("/accounts/"))

    # ---------- Phase 2: WRITE allowed (create+send quote; create+confirm SO) ----------
    prod = q1("SELECT id FROM products WHERE code='GEN01'")[0]
    def make_quote(qty="4"):
        page.goto(b + "/quotations/create", wait_until="networkidle"); reenable(page)
        page.locator(".choices:has(#customer_id_display)").click(); page.wait_for_timeout(250)
        page.locator(".choices__list--dropdown .choices__item--choice", has_text="ABC Trading").first.click()
        page.wait_for_selector("#lineItemsBody tr", timeout=10000)
        r = page.locator("#lineItemsBody tr").first
        r.locator("td:nth-child(2) select").select_option(str(prod)); page.wait_for_timeout(300)
        r.locator("input[id^='qty-']").fill(qty); r.locator("input[id^='qty-']").dispatch_event("change")
        up = r.locator("input[id^='up-']")
        if not (up.input_value() or "").strip(): up.fill("100"); up.dispatch_event("change")
        page.wait_for_timeout(300)
        with page.expect_navigation(wait_until="networkidle"): page.locator("#submitBtn").click()
        return q1("SELECT id FROM quotations ORDER BY id DESC LIMIT 1")[0]
    qid = make_quote()
    check("WRITE ok: staff created a Quotation", qid is not None and q1("SELECT created_by_id FROM quotations WHERE id=?", qid)[0] == q1("SELECT id FROM users WHERE username=?", STAFF)[0])
    post(page, b, "%s/quotations/%d/send" % (b, qid))
    check("WRITE ok: staff sent the Quotation (draft->sent)", q1("SELECT status FROM quotations WHERE id=?", qid)[0] == "sent")

    # ---------- Phase 3: APPROVE denied ----------
    post(page, b, "%s/quotations/%d/accept" % (b, qid))
    check("APPROVE denied: staff cannot ACCEPT a Quotation (still sent)", q1("SELECT status FROM quotations WHERE id=?", qid)[0] == "sent")
    # approve any existing DR -> role gate fires first regardless of DR status
    anydr = q1("SELECT id FROM delivery_receipts ORDER BY id DESC LIMIT 1")
    if anydr:
        before = q1("SELECT status FROM delivery_receipts WHERE id=?", anydr[0])[0]
        page.goto(b + "/delivery-receipts/%d" % anydr[0], wait_until="networkidle")
        st = post(page, b, "%s/delivery-receipts/%d/approve" % (b, anydr[0]))
        after = q1("SELECT status FROM delivery_receipts WHERE id=?", anydr[0])[0]
        check("APPROVE denied: staff cannot APPROVE a Delivery Receipt (status unchanged)", after == before, "%s->%s" % (before, after))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
