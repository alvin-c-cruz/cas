"""Tier 6a: create a Quotation via the UI as admin, adding the CUSTOMER inline
(quick-add modal) and using product GEN01 on the line. Verifies the quote + line persist.
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

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=250)
    b = harness.base_url()
    harness.login(page, "admin")
    page.goto(b + "/quotations/create", wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>{e.removeAttribute('readonly');})")

    # header defaults: quotation_date prefilled today; vat_treatment default inclusive
    check("quotation form loaded (date prefilled)", bool(page.input_value("input[name='quotation_date']")),
          "date=%r" % page.input_value("input[name='quotation_date']"))

    # ---- inline ADD CUSTOMER via the Choices picker '+ Add Customer...' ----
    cwrap = page.locator(".choices:has(#customer_id_display)")
    cwrap.click(); page.wait_for_timeout(300)
    page.locator(".choices__list--dropdown .choices__item--choice", has_text="Add Customer").first.click()
    page.wait_for_selector("#customerQuickAddOverlay", state="visible", timeout=8000)
    modal = page.locator("#customerQuickAddForm")
    modal.locator("input[name='code']").fill("CUST01")
    modal.locator("input[name='name']").fill("ABC Trading Corporation")
    if modal.locator("input[name='tin']").count():
        modal.locator("input[name='tin']").fill("222-333-444-00000")
    page.click("#customerQuickAddSubmit")

    # wait: modal closes + customer selected + first line auto-added
    page.wait_for_selector("#customerQuickAddOverlay", state="hidden", timeout=10000)
    cust = q1("SELECT id,code,name FROM customers WHERE code='CUST01'")
    check("inline customer created", cust is not None, str(cust))
    page.wait_for_selector("#lineItemsBody tr", timeout=10000)
    check("customer selected -> line-items unlocked (first line added)",
          page.locator("#lineItemsBody tr").count() >= 1)

    # ---- fill the line with GEN01 ----
    row = page.locator("#lineItemsBody tr").first
    # product select (plain <select> with onProductPick)
    prod = q1("SELECT id FROM products WHERE code='GEN01'")[0]
    row.locator("td:nth-child(2) select").select_option(str(prod))
    page.wait_for_timeout(400)   # onProductPick fills uom + unit price
    # qty
    row.locator("input[id^='qty-']").fill("10")
    row.locator("input[id^='qty-']").dispatch_event("change")
    # ensure unit price (product default may already fill 100)
    up = row.locator("input[id^='up-']")
    if not (up.input_value() or "").strip():
        up.fill("100"); up.dispatch_event("change")
    page.wait_for_timeout(400)

    total = page.inner_text("#totalDisplay")
    check("line total computed (qty*price)", total not in ("", "0.00"), "total=%s" % total)

    # ---- submit ----
    submit = page.locator("#submitBtn")
    check("submit enabled once valid", not submit.is_disabled())
    with page.expect_navigation(wait_until="networkidle"):
        submit.click()
    qn = q1("SELECT id,quotation_number,customer_id,total_amount FROM quotations ORDER BY id DESC LIMIT 1")
    check("QUOTATION created", qn is not None, str(qn))
    if qn:
        li = q1("SELECT COUNT(*), SUM(amount) FROM quotation_items WHERE quotation_id=?", qn[0])
        check("quotation line persisted", li and li[0] >= 1, "lines=%s sum=%s" % (li[0], li[1]))
        check("quote linked to inline customer", qn[2] == (cust[0] if cust else None))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
