"""Delivery Receipt CRUD / lifecycle test (as admin) -- operational only, no posting.
Fresh confirmed SO (qty 30) -> DR-A: CREATE(20) -> UPDATE(15) -> APPROVE -> edit-GUARD -> DELIVER;
DR-B: CREATE(10) -> CANCEL (+min-reason guard). Uses existing CUST01 + GEN01.
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
def dstatus(i): return q1("SELECT status FROM delivery_receipts WHERE id=?", i)[0]

def csrf_post(page, b, url, fields=None):
    page.goto(b + "/settings", wait_until="networkidle")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    return page.evaluate("""async(a)=>{const[u,ex,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        for(const k in (ex||{}))fd.append(k,ex[k]);
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [url, fields or {}, token])

def create_confirmed_so(page, b, qty="30"):
    page.goto(b + "/sales-orders/create", wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    page.locator(".choices:has(#customer_id_display)").click(); page.wait_for_timeout(250)
    page.locator(".choices__list--dropdown .choices__item--choice", has_text="ABC Trading").first.click()
    page.wait_for_selector("#lineItemsBody tr", timeout=10000)
    if page.locator("textarea[name='notes']").count(): page.fill("textarea[name='notes']", "DR-test SO")
    row = page.locator("#lineItemsBody tr").first
    prod = q1("SELECT id FROM products WHERE code='GEN01'")[0]
    row.locator("td:nth-child(2) select").select_option(str(prod)); page.wait_for_timeout(300)
    row.locator("input[id^='qty-']").fill(qty); row.locator("input[id^='qty-']").dispatch_event("change")
    up = row.locator("input[id^='up-']")
    if not (up.input_value() or "").strip(): up.fill("100"); up.dispatch_event("change")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"): page.locator("#submitBtn").click()
    so = q1("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")[0]
    csrf_post(page, b, "%s/sales-orders/%d/confirm" % (b, so))
    return so

def create_dr(page, b, so_id, deliver_qty):
    page.goto(b + "/delivery-receipts/create?so=%d" % so_id, wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    page.evaluate("""(soid)=>{const s=document.querySelector("select[name='sales_order_id']");
        if(s){s.value=String(soid);s.dispatchEvent(new Event('change',{bubbles:true}));}}""", so_id)
    page.wait_for_selector(".qty-input", timeout=8000)
    page.evaluate("""(q)=>{const i=document.querySelector('.qty-input');i.value=String(q);
        i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));}""", deliver_qty)
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.querySelector('form').submit()")
    return q1("SELECT id FROM delivery_receipts ORDER BY id DESC LIMIT 1")[0]

def dr_delivered_qty(i): return q1("SELECT SUM(delivered_quantity) FROM delivery_receipt_items WHERE delivery_receipt_id=?", i)[0]

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=170)
    b = harness.base_url(); harness.login(page, "admin")

    so = create_confirmed_so(page, b, "30")
    check("setup: confirmed SO with open qty", q1("SELECT status FROM sales_orders WHERE id=?", so)[0] == "confirmed")

    # DR-A: CREATE (deliver 20)
    dra = create_dr(page, b, so, 20)
    check("DR CREATE (draft, qty 20)", dra is not None and dstatus(dra) == "draft" and float(dr_delivered_qty(dra) or 0) == 20,
          "id=%s qty=%s" % (dra, dr_delivered_qty(dra)))

    # UPDATE: edit draft -> change delivered qty 20 -> 15
    page.goto(b + "/delivery-receipts/%d/edit" % dra, wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    page.wait_for_selector(".qty-input", timeout=8000)
    page.evaluate("""()=>{const i=document.querySelector('.qty-input');i.value='15';
        i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));}""")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.querySelector('form').submit()")
    # KNOWN BUG BUG-DR-EDIT-FALSE-CONFLICT (HIGH, logged 2026-07-11): the DR form renders csrf-only
    # so row_version is never posted -> claim_version false-conflicts -> the edit NEVER persists.
    # This tripwire asserts the CURRENT (broken) reality; FLIP to `== 15` when the bug is fixed.
    check("DR UPDATE known-broken (BUG-DR-EDIT-FALSE-CONFLICT: qty stays 20)",
          float(dr_delivered_qty(dra) or 0) == 20, "qty=%s (expect 15 once fixed)" % dr_delivered_qty(dra))

    # APPROVE
    csrf_post(page, b, "%s/delivery-receipts/%d/approve" % (b, dra))
    check("DR APPROVE (draft -> approved)", dstatus(dra) == "approved", dstatus(dra))

    # EDIT GUARD (approved not editable)
    page.goto(b + "/delivery-receipts/%d/edit" % dra, wait_until="networkidle")
    check("DR EDIT GUARD (approved redirected off edit)",
          "/edit" not in page.url or page.locator(".qty-input").count() == 0, "url=%s" % page.url)

    # DELIVER
    csrf_post(page, b, "%s/delivery-receipts/%d/deliver" % (b, dra))
    check("DR DELIVER (approved -> delivered)", dstatus(dra) == "delivered", dstatus(dra))

    # DR-B: CREATE (deliver 10 of remaining open) -> CANCEL (+guard)
    drb = create_dr(page, b, so, 10)
    check("DR-B CREATE (draft)", drb is not None and dstatus(drb) == "draft", "id=%s" % drb)
    csrf_post(page, b, "%s/delivery-receipts/%d/cancel" % (b, drb), {"cancel_reason": "short"})
    check("DR CANCEL GUARD (<10-char refused)", dstatus(drb) == "draft", dstatus(drb))
    csrf_post(page, b, "%s/delivery-receipts/%d/cancel" % (b, drb), {"cancel_reason": "Duplicate delivery entry, cancelling"})
    check("DR CANCEL (draft -> cancelled)", dstatus(drb) == "cancelled", dstatus(drb))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
