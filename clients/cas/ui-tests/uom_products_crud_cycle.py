"""UOM + Products CRUD test (as admin, direct-save), then encode the real 'Pieces' UOM.

UOM and Products have NO hard-delete route -- master data referenced by transactions is
retired by DEACTIVATE (edit -> status Inactive), not deleted. So the cycle tested is
Create -> Read(list) -> Update -> Deactivate. Products depend on a UOM existing, so the
real 'Pieces' is encoded between the two so the Products test can reference it.
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
def set_status(page, val):
    page.eval_on_selector("select[name='is_active']","(e,v)=>{e.value=v;e.dispatchEvent(new Event('change',{bubbles:true}));}", val)
def submit_code(page):
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.querySelector(\"input[name='code']\").form.submit()")
def body_has(page, t):
    for _ in range(12):
        try: return t.lower() in page.content().lower()
        except Exception: page.wait_for_timeout(200)
    return t.lower() in page.content().lower()
def sel_by_label(page, name, needle):
    return page.evaluate("""(a)=>{const[n,x]=a;const s=document.querySelector("select[name='"+n+"']");
        if(!s)return null;for(const o of s.options){if(o.textContent.includes(x)){s.value=o.value;
        s.dispatchEvent(new Event('change',{bubbles:true}));return o.value;}}return null;}""", [name, needle])

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=140)
    b = harness.base_url()
    harness.login(page, "admin")

    # ================= UOM CRUD (create/read/update/deactivate) =================
    page.goto(b + "/units-of-measure/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "TESTU"); page.fill("input[name='name']", "Test Unit")
    set_status(page, "1"); reenable(page); submit_code(page)
    row = q1("SELECT id,is_active FROM units_of_measure WHERE code='TESTU'")
    check("UOM CREATE", row is not None, str(row)); uid = row[0] if row else None
    page.goto(b + "/units-of-measure", wait_until="networkidle")
    check("UOM READ (list)", body_has(page, "TESTU") and body_has(page, "Test Unit"))
    if uid:
        page.goto(b + "/units-of-measure/%d/edit" % uid, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "Test Unit EDITED"); reenable(page); submit_code(page)
        check("UOM UPDATE", q1("SELECT name FROM units_of_measure WHERE id=?", uid)[0] == "Test Unit EDITED")
        page.goto(b + "/units-of-measure/%d/edit" % uid, wait_until="networkidle"); reenable(page)
        set_status(page, "0"); reenable(page); submit_code(page)
        check("UOM DEACTIVATE (no hard delete)", q1("SELECT is_active FROM units_of_measure WHERE id=?", uid)[0] in (0, "0", False))

    # ================= encode the real 'Pieces' UOM =================
    page.goto(b + "/units-of-measure/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "PCS"); page.fill("input[name='name']", "Pieces")
    set_status(page, "1"); reenable(page); submit_code(page)
    pcs = q1("SELECT id,is_active FROM units_of_measure WHERE code='PCS'")
    check("encoded UOM 'Pieces' (active)", pcs is not None and pcs[1] in (1, "1", True), str(pcs))

    # ================= Products CRUD (references Pieces) =================
    page.goto(b + "/products/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", "TESTP"); page.fill("input[name='name']", "Test Product")
    sel_by_label(page, "default_unit_of_measure_id", "Pieces")       # plain select
    sel_by_label(page, "default_account_id", "Sales Revenue")        # optional, plain select
    if page.locator("input[name='default_unit_price']").count():
        page.fill("input[name='default_unit_price']", "100.00")
    set_status(page, "1"); reenable(page); submit_code(page)
    row = q1("SELECT id,default_unit_of_measure_id FROM products WHERE code='TESTP'")
    check("PRODUCT CREATE (refs Pieces UOM)", row is not None and row[1] == (pcs[0] if pcs else None), str(row))
    pid = row[0] if row else None
    page.goto(b + "/products", wait_until="networkidle")
    check("PRODUCT READ (list)", body_has(page, "TESTP") and body_has(page, "Test Product"))
    if pid:
        page.goto(b + "/products/%d/edit" % pid, wait_until="networkidle"); reenable(page)
        page.fill("input[name='name']", "Test Product EDITED"); reenable(page); submit_code(page)
        check("PRODUCT UPDATE", q1("SELECT name FROM products WHERE id=?", pid)[0] == "Test Product EDITED")
        page.goto(b + "/products/%d/edit" % pid, wait_until="networkidle"); reenable(page)
        set_status(page, "0"); reenable(page); submit_code(page)
        check("PRODUCT DEACTIVATE (no hard delete)", q1("SELECT is_active FROM products WHERE id=?", pid)[0] in (0, "0", False))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
