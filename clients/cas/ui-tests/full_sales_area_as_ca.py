"""Full Sales Area driven as the CHIEF ACCOUNTANT (uitest_ca).

O2C spine as CA: Quotation create+send -> Accept -> SO -> confirm -> DR create -> approve
-> deliver -> Sales Invoice (expected BLOCKED by the known HIGH bug
BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS, proving it's role-independent). Also exercises the
CA-gated lifecycle actions (accept/confirm/approve/deliver all require can_approve, which CA holds).
"""
import sys, sqlite3
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
CA = "uitest_ca"
results = []
def check(n, ok, d=""):
    results.append((bool(ok), n, d)); print(("PASS " if ok else "FAIL ") + n + (("  -- " + d) if d else ""))
def q1(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchone()
def body_has(page, t):
    for _ in range(12):
        try: return t.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
    return t.lower() in page.content().lower()

_TOKEN = {"v": None}
def csrf(page, b):
    # CA can't reach /settings (admin-panel). Source a session CSRF token from a CA-accessible form.
    if _TOKEN["v"] is None:
        page.goto(b + "/accounts/create", wait_until="networkidle")
        _TOKEN["v"] = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    return _TOKEN["v"]
def post(page, b, url, fields=None):
    t = csrf(page, b)
    return page.evaluate("""async(a)=>{const[u,ex,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        for(const k in (ex||{}))fd.append(k,ex[k]);
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [url, fields or {}, t])

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=170)
    b = harness.base_url()
    landed = harness.login(page, CA)
    check("logged in as Chief Accountant", "/login" not in landed, landed)
    prod = q1("SELECT id FROM products WHERE code='GEN01'")[0]
    SALES_ACCT = q1("SELECT id FROM accounts WHERE code='4110'")[0]

    # 1) Quotation create (CUST01 + GEN01 x12) -> send -> accept
    page.goto(b + "/quotations/create", wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    page.locator(".choices:has(#customer_id_display)").click(); page.wait_for_timeout(250)
    page.locator(".choices__list--dropdown .choices__item--choice", has_text="ABC Trading").first.click()
    page.wait_for_selector("#lineItemsBody tr", timeout=10000)
    row = page.locator("#lineItemsBody tr").first
    row.locator("td:nth-child(2) select").select_option(str(prod)); page.wait_for_timeout(300)
    row.locator("input[id^='qty-']").fill("12"); row.locator("input[id^='qty-']").dispatch_event("change")
    up = row.locator("input[id^='up-']")
    if not (up.input_value() or "").strip(): up.fill("100"); up.dispatch_event("change")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"): page.locator("#submitBtn").click()
    qid = q1("SELECT id FROM quotations ORDER BY id DESC LIMIT 1")[0]
    check("CA: Quotation created", qid is not None)
    post(page, b, "%s/quotations/%d/send" % (b, qid))
    check("CA: Quotation sent (draft->sent)", q1("SELECT status FROM quotations WHERE id=?", qid)[0] == "sent")
    post(page, b, "%s/quotations/%d/accept" % (b, qid))
    check("CA: Quotation accepted (sent->accepted)", q1("SELECT status FROM quotations WHERE id=?", qid)[0] == "accepted")

    # 2) SO created by accept -> confirm
    so = q1("SELECT id,status FROM sales_orders ORDER BY id DESC LIMIT 1")
    check("CA: Accept spawned a Sales Order (draft)", so and so[1] == "draft", str(so))
    so_id = so[0]
    post(page, b, "%s/sales-orders/%d/confirm" % (b, so_id))
    check("CA: SO confirmed (draft->confirmed)", q1("SELECT status FROM sales_orders WHERE id=?", so_id)[0] == "confirmed")

    # 3) DR create against SO -> approve -> deliver
    page.goto(b + "/delivery-receipts/create?so=%d" % so_id, wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    page.evaluate("""(s)=>{const el=document.querySelector("select[name='sales_order_id']");if(el){el.value=String(s);el.dispatchEvent(new Event('change',{bubbles:true}));}}""", so_id)
    page.wait_for_selector(".qty-input", timeout=8000)
    page.evaluate("""()=>{const i=document.querySelector('.qty-input');const open=i.getAttribute('max')||'12';i.value=open;i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));}""")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"): page.evaluate("()=>document.querySelector('form').submit()")
    dr = q1("SELECT id,status FROM delivery_receipts ORDER BY id DESC LIMIT 1")
    check("CA: DR created against SO (draft)", dr and dr[1] == "draft", str(dr))
    dr_id = dr[0]
    post(page, b, "%s/delivery-receipts/%d/approve" % (b, dr_id))
    check("CA: DR approved", q1("SELECT status FROM delivery_receipts WHERE id=?", dr_id)[0] == "approved")
    post(page, b, "%s/delivery-receipts/%d/deliver" % (b, dr_id))
    check("CA: DR delivered", q1("SELECT status FROM delivery_receipts WHERE id=?", dr_id)[0] == "delivered")

    # 4) Sales Invoice: attempt -> expected BLOCKED by BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS
    cust_id = q1("SELECT customer_id FROM delivery_receipts WHERE id=?", dr_id)[0]
    line = [{"product_id": prod, "quantity": "12", "unit_price": "100", "amount": "1200.00",
             "vat_category": "V12", "account_id": SALES_ACCT, "description": ""}]
    si_before = q1("SELECT COUNT(*) FROM sales_invoices")[0]
    page.goto(b + "/sales-invoices/create", wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    page.locator(".choices:has(#customer_id)").click(); page.wait_for_timeout(250)
    page.locator(".choices__list--dropdown .choices__item--choice", has_text="ABC Trading").first.click()
    page.fill("textarea[name='notes']", "CA full-sales-area test")
    page.evaluate("""(a)=>{const[li,dr]=a;document.getElementById('lineItemsData').value=JSON.stringify(li);
        const s=document.getElementById('sourceDrIds');if(s)s.value=JSON.stringify([dr]);}""", [line, dr_id])
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.getElementById('lineItemsData').form.submit()")
    si_after = q1("SELECT COUNT(*) FROM sales_invoices")[0]
    blocked = si_after == si_before and body_has(page, "not found in coa")
    check("CA: Sales Invoice BLOCKED by hardcoded-AR bug (role-independent, KNOWN BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS)",
          blocked, "si_before=%d si_after=%d" % (si_before, si_after))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
