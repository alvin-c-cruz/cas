"""Customers + Vendors full CRUD test (as admin, direct-save on disposable codes).

Both modules are direct-save (no approval workflow). Create -> Read(list) -> Update -> Delete.
VAT/WT selects are plain (customer: sales-VAT name + WHT code; vendor: purchase-VAT code, required).
Leaves real data untouched (creates + deletes ZZ* codes).
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
def reenable(page):
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>{e.removeAttribute('readonly');e.removeAttribute('disabled');})")
def set_active(page):
    page.eval_on_selector("select[name='is_active']","e=>{e.value='1';e.dispatchEvent(new Event('change',{bubbles:true}));}")
def submit_code(page):
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.querySelector(\"input[name='code']\").form.submit()")
def body_has(page, t):
    for _ in range(12):
        try: return t.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
    return t.lower() in page.content().lower()
def sel_by_label_contains(page, name, needle):
    """Select an <option> whose text contains needle; returns its value. (plain select)"""
    return page.evaluate("""(a)=>{const[n,x]=a;const s=document.querySelector("select[name='"+n+"']");
        for(const o of s.options){if(o.textContent.includes(x)){s.value=o.value;
            s.dispatchEvent(new Event('change',{bubbles:true}));return o.value;}}return null;}""", [name, needle])
def pick_choices(page, name, needle):
    """Choices.js-enhanced select (strips native options) -- open + mousedown/click the choice."""
    wrap = page.locator(".choices:has(select[name='%s'])" % name)
    wrap.click(); page.wait_for_timeout(250)
    opt = wrap.locator(".choices__list--dropdown .choices__item--choice", has_text=needle)
    opt.first.dispatch_event("mousedown"); opt.first.dispatch_event("click")
def delete_via_fetch(page, list_url, del_url):
    page.goto(list_url, wait_until="networkidle")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    return page.evaluate("""async (a)=>{const[u,t]=a;const fd=new FormData();fd.append('csrf_token',t);
        const r=await fetch(u,{method:'POST',body:fd});return r.status;}""", [del_url, token])

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=150)
    b = harness.base_url()
    harness.login(page, "admin")

    # ================= CUSTOMER =================
    page.goto(b + "/customers/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "ZZCUST"); page.fill("input[name='name']", "CRUD Test Customer")
    page.fill("input[name='tin']", "111-222-333-00000")
    page.select_option("select[name='payment_terms']", "Net 30")
    sel_by_label_contains(page, "default_vat_category", "VATable Sales")   # sales VAT by name
    # (customer WHT is an optional m2m multi-select `withholding_tax_ids`; skipped here)
    set_active(page); reenable(page); submit_code(page)
    row = q1("SELECT id FROM customers WHERE code='ZZCUST'")
    check("CUSTOMER CREATE", row is not None, str(row)); cid = row[0] if row else None
    page.goto(b + "/customers", wait_until="networkidle")
    check("CUSTOMER READ (list)", body_has(page, "ZZCUST") and body_has(page, "CRUD Test Customer"))
    if cid:
        page.goto(b + "/customers/%d/edit" % cid, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "CRUD Customer EDITED"); reenable(page); submit_code(page)
        check("CUSTOMER UPDATE", q1("SELECT name FROM customers WHERE id=?", cid)[0] == "CRUD Customer EDITED",
              q1("SELECT name FROM customers WHERE id=?", cid)[0])
        st = delete_via_fetch(page, b + "/customers", b + "/customers/%d/delete" % cid)
        check("CUSTOMER DELETE", q1("SELECT id FROM customers WHERE code='ZZCUST'") is None, "http " + str(st))

    # ================= VENDOR =================
    page.goto(b + "/vendors/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "ZZVEND"); page.fill("input[name='name']", "CRUD Test Vendor")
    page.fill("input[name='tin']", "444-555-666-00000")
    page.select_option("select[name='payment_terms']", "Net 30")
    pick_choices(page, "default_vat_category", "V12DG")   # purchase VAT (Choices-enhanced, REQUIRED)
    set_active(page); reenable(page); submit_code(page)
    row = q1("SELECT id FROM vendors WHERE code='ZZVEND'")
    check("VENDOR CREATE", row is not None, str(row)); did = row[0] if row else None
    page.goto(b + "/vendors", wait_until="networkidle")
    check("VENDOR READ (list)", body_has(page, "ZZVEND") and body_has(page, "CRUD Test Vendor"))
    if did:
        page.goto(b + "/vendors/%d/edit" % did, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "CRUD Vendor EDITED"); reenable(page); submit_code(page)
        check("VENDOR UPDATE", q1("SELECT name FROM vendors WHERE id=?", did)[0] == "CRUD Vendor EDITED",
              q1("SELECT name FROM vendors WHERE id=?", did)[0])
        st = delete_via_fetch(page, b + "/vendors", b + "/vendors/%d/delete" % did)
        check("VENDOR DELETE", q1("SELECT id FROM vendors WHERE code='ZZVEND'") is None, "http " + str(st))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
