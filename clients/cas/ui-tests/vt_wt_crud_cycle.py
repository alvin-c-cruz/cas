"""VT/WT full CRUD test (as admin, auto-approved) on disposable entries.

Covers purchase VAT categories, sales VAT categories, and withholding tax:
Create -> Read(list) -> Update -> Delete. Admin is sole full-access so mutations
auto-apply immediately. Uses vatable/regular natures so the (Choices) account
picker is visible. Leaves real master data untouched (creates + deletes ZZ* codes).
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
def submit_code(page):
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.querySelector(\"input[name='code']\").form.submit()")
def body_has(page, t):
    for _ in range(12):
        try: return t.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
    return t.lower() in page.content().lower()
def set_active(page):
    page.eval_on_selector("select[name='is_active']",
        "e=>{e.value='1';e.dispatchEvent(new Event('change',{bubbles:true}));}")
def pick_account(page, name, code):
    wrap = page.locator(".choices:has(select[name='%s'])" % name)
    wrap.wait_for(state="visible", timeout=10000)
    wrap.click(); page.wait_for_timeout(250)
    opt = wrap.locator(".choices__list--dropdown .choices__item--choice", has_text=code + " :")
    opt.first.dispatch_event("mousedown"); opt.first.dispatch_event("click")
def delete_via_fetch(page, list_url, del_url, reason):
    page.goto(list_url, wait_until="networkidle")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    return page.evaluate("""async (a)=>{const[u,r,t]=a;const fd=new FormData();
        fd.append('request_reason',r);fd.append('csrf_token',t);
        const resp=await fetch(u,{method:'POST',body:fd});return resp.status;}""", [del_url, reason, token])

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=150)
    b = harness.base_url()
    harness.login(page, "admin")

    # ============ Purchase VAT ============
    page.goto(b + "/vat-categories/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "ZZV"); page.fill("input[name='name']", "CRUD Purchase VAT"); page.fill("input[name='rate']", "12")
    page.select_option("select[name='transaction_nature']", "domestic_goods")
    pick_account(page, "input_vat_account_id", "1720")
    set_active(page); reenable(page); submit_code(page)
    row = q1("SELECT id FROM vat_categories WHERE code='ZZV'")
    check("VT CREATE (auto-approved)", row is not None, str(row)); vid = row[0] if row else None
    page.goto(b + "/vat-categories/", wait_until="networkidle")
    check("VT READ (list shows it)", body_has(page, "ZZV") and body_has(page, "CRUD Purchase VAT"))
    if vid:
        page.goto(b + "/vat-categories/%d/edit" % vid, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "CRUD Purchase VAT EDITED"); page.fill("textarea[name='request_reason']", "edit test"); reenable(page); submit_code(page)
        check("VT UPDATE", q1("SELECT name FROM vat_categories WHERE id=?", vid)[0] == "CRUD Purchase VAT EDITED")
        st = delete_via_fetch(page, b + "/vat-categories/", b + "/vat-categories/%d/delete" % vid, "del test")
        check("VT DELETE", q1("SELECT id FROM vat_categories WHERE code='ZZV'") is None, "http " + str(st))

    # ============ Sales VAT ============
    page.goto(b + "/sales-vat-categories/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "ZZS"); page.fill("input[name='name']", "CRUD Sales VAT"); page.fill("input[name='rate']", "12")
    page.select_option("select[name='transaction_nature']", "regular")
    pick_account(page, "output_vat_account_id", "2310")
    set_active(page); reenable(page); submit_code(page)
    row = q1("SELECT id FROM sales_vat_categories WHERE code='ZZS'")
    check("Sales VT CREATE", row is not None, str(row)); sid = row[0] if row else None
    if sid:
        page.goto(b + "/sales-vat-categories/%d/edit" % sid, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "CRUD Sales VAT EDITED"); page.fill("textarea[name='request_reason']", "edit test"); reenable(page); submit_code(page)
        check("Sales VT UPDATE", q1("SELECT name FROM sales_vat_categories WHERE id=?", sid)[0] == "CRUD Sales VAT EDITED")
        st = delete_via_fetch(page, b + "/sales-vat-categories/", b + "/sales-vat-categories/%d/delete" % sid, "del test")
        check("Sales VT DELETE", q1("SELECT id FROM sales_vat_categories WHERE code='ZZS'") is None, "http " + str(st))

    # ============ Withholding Tax ============
    page.goto(b + "/withholding-tax/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "ZZW"); page.fill("input[name='name']", "CRUD WHT"); page.fill("input[name='rate']", "2")
    page.select_option("select[name='tax_type']", "expanded")
    pick_account(page, "payable_account_id", "2320")
    pick_account(page, "receivable_account_id", "1710")
    set_active(page); reenable(page); submit_code(page)
    row = q1("SELECT id FROM withholding_tax WHERE code='ZZW'")
    check("WHT CREATE", row is not None, str(row)); wid = row[0] if row else None
    if wid:
        page.goto(b + "/withholding-tax/%d/edit" % wid, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "CRUD WHT EDITED"); page.fill("textarea[name='request_reason']", "edit test"); reenable(page); submit_code(page)
        check("WHT UPDATE", q1("SELECT name FROM withholding_tax WHERE id=?", wid)[0] == "CRUD WHT EDITED")
        st = delete_via_fetch(page, b + "/withholding-tax/", b + "/withholding-tax/%d/delete" % wid, "del test")
        check("WHT DELETE", q1("SELECT id FROM withholding_tax WHERE code='ZZW'") is None, "http " + str(st))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
