"""Sales Order CRUD / lifecycle test (as admin) -- standalone, no posting to books.
Covers: CREATE (CUST01+GEN01), UPDATE (edit draft), CONFIRM (draft->confirmed),
edit-GUARD (confirmed not editable), CANCEL path (+min-reason guard). Uses existing
active customer CUST01 + product GEN01.
"""
import sys, sqlite3
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
results = []
def check(n, ok, d=""):
    results.append((bool(ok), n, d)); print(("PASS " if ok else "FAIL ") + n + (("  -- " + d) if d else ""))
def q1(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchone()
def status(soid): return q1("SELECT status FROM sales_orders WHERE id=?", soid)[0]

def create_so(page, b, qty="10"):
    page.goto(b + "/sales-orders/create", wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    cw = page.locator(".choices:has(#customer_id_display)")
    cw.click(); page.wait_for_timeout(250)
    page.locator(".choices__list--dropdown .choices__item--choice", has_text="ABC Trading").first.click()
    page.wait_for_selector("#lineItemsBody tr", timeout=10000)
    if page.locator("textarea[name='notes']").count():
        page.fill("textarea[name='notes']", "SO CRUD test order")
    row = page.locator("#lineItemsBody tr").first
    prod = q1("SELECT id FROM products WHERE code='GEN01'")[0]
    row.locator("td:nth-child(2) select").select_option(str(prod)); page.wait_for_timeout(300)
    row.locator("input[id^='qty-']").fill(qty); row.locator("input[id^='qty-']").dispatch_event("change")
    up = row.locator("input[id^='up-']")
    if not (up.input_value() or "").strip(): up.fill("100"); up.dispatch_event("change")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"):
        page.locator("#submitBtn").click()
    return q1("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")[0]

def csrf_post(page, b, url, fields=None):
    page.goto(b + "/settings", wait_until="networkidle")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    return page.evaluate("""async(a)=>{const[u,ex,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        for(const k in (ex||{}))fd.append(k,ex[k]);
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [url, fields or {}, token])

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=180)
    b = harness.base_url(); harness.login(page, "admin")

    # CREATE
    so = create_so(page, b, "10")
    check("SO CREATE (draft)", so is not None and status(so) == "draft",
          "id=%s total=%s" % (so, q1("SELECT total_amount FROM sales_orders WHERE id=?", so)[0]))

    # UPDATE: edit draft -> qty 10 -> 25
    page.goto(b + "/sales-orders/%d/edit" % so, wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    row = page.locator("#lineItemsBody tr").first
    row.locator("input[id^='qty-']").fill("25"); row.locator("input[id^='qty-']").dispatch_event("change")
    page.wait_for_timeout(400)
    with page.expect_navigation(wait_until="networkidle"):
        page.locator("#submitBtn").click()
    check("SO UPDATE (qty 25 -> total 2500)",
          str(q1("SELECT total_amount FROM sales_orders WHERE id=?", so)[0]) in ("2500","2500.0","2500.00"),
          "total=%s" % q1("SELECT total_amount FROM sales_orders WHERE id=?", so)[0])

    # CONFIRM
    csrf_post(page, b, "%s/sales-orders/%d/confirm" % (b, so))
    check("SO CONFIRM (draft -> confirmed)", status(so) == "confirmed", status(so))

    # EDIT GUARD (confirmed not editable)
    page.goto(b + "/sales-orders/%d/edit" % so, wait_until="networkidle")
    check("SO EDIT GUARD (confirmed redirected off edit)",
          "/edit" not in page.url or page.locator("#lineItemsBody").count() == 0, "url=%s" % page.url)

    # CANCEL path on a fresh draft SO (+ guard)
    so2 = create_so(page, b, "5")
    csrf_post(page, b, "%s/sales-orders/%d/cancel" % (b, so2), {"cancel_reason": "short"})
    check("SO CANCEL GUARD (<10-char reason refused)", status(so2) == "draft", status(so2))
    csrf_post(page, b, "%s/sales-orders/%d/cancel" % (b, so2), {"cancel_reason": "Ordered in error, customer withdrew"})
    check("SO CANCEL (draft -> cancelled)", status(so2) == "cancelled", status(so2))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
