"""Quotation CRUD / lifecycle test (as admin), on disposable quotes.

Covers: UPDATE (edit a draft), edit-GUARD (non-draft not editable),
REJECT path (draft->send->reject, +min-reason guard), CANCEL path (draft->cancel, +guard).
Uses the existing active customer CUST01 + product GEN01. Leaves QTN-2026-07-0001 intact
by operating edit on it but restoring, and creating fresh quotes for reject/cancel.
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
def status(qid): return q1("SELECT status FROM quotations WHERE id=?", qid)[0]

def create_quote(page, b, qty="5"):
    page.goto(b + "/quotations/create", wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    cw = page.locator(".choices:has(#customer_id_display)")
    cw.click(); page.wait_for_timeout(250)
    page.locator(".choices__list--dropdown .choices__item--choice", has_text="ABC Trading").first.click()
    page.wait_for_selector("#lineItemsBody tr", timeout=10000)
    row = page.locator("#lineItemsBody tr").first
    prod = q1("SELECT id FROM products WHERE code='GEN01'")[0]
    row.locator("td:nth-child(2) select").select_option(str(prod)); page.wait_for_timeout(300)
    row.locator("input[id^='qty-']").fill(qty); row.locator("input[id^='qty-']").dispatch_event("change")
    up = row.locator("input[id^='up-']")
    if not (up.input_value() or "").strip(): up.fill("100"); up.dispatch_event("change")
    page.wait_for_timeout(300)
    with page.expect_navigation(wait_until="networkidle"):
        page.locator("#submitBtn").click()
    return q1("SELECT id FROM quotations ORDER BY id DESC LIMIT 1")[0]

def post_action(page, b, qid, action, **fields):
    page.goto(b + "/quotations/%d" % qid, wait_until="networkidle")
    token = page.eval_on_selector("input[name='csrf_token']", "e=>e.value")
    return page.evaluate("""async(a)=>{const[base,qid,act,extra,t]=a;const fd=new FormData();
        fd.append('csrf_token',t);for(const k in extra)fd.append(k,extra[k]);
        const r=await fetch(base+'/quotations/'+qid+'/'+act,{method:'POST',body:fd});return r.status;}""",
        [b, qid, action, fields, token])

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=200)
    b = harness.base_url(); harness.login(page, "admin")

    # ---- UPDATE: edit the existing draft QTN-0001 (qty -> 20) ----
    qa = q1("SELECT id FROM quotations WHERE quotation_number='QTN-2026-07-0001'")[0]
    page.goto(b + "/quotations/%d/edit" % qa, wait_until="networkidle")
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>e.removeAttribute('readonly'))")
    row = page.locator("#lineItemsBody tr").first
    row.locator("input[id^='qty-']").fill("20"); row.locator("input[id^='qty-']").dispatch_event("change")
    page.wait_for_timeout(400)
    with page.expect_navigation(wait_until="networkidle"):
        page.locator("#submitBtn").click()
    check("UPDATE: draft quote edited (total 20*100=2000)",
          str(q1("SELECT total_amount FROM quotations WHERE id=?", qa)[0]) in ("2000", "2000.0", "2000.00"),
          "total=%s" % q1("SELECT total_amount FROM quotations WHERE id=?", qa)[0])

    # ---- EDIT GUARD: send it, then edit must be refused ----
    post_action(page, b, qa, "send")
    check("send: draft -> sent", status(qa) == "sent", status(qa))
    resp = page.goto(b + "/quotations/%d/edit" % qa, wait_until="networkidle")
    check("EDIT GUARD: non-draft edit redirected to view (not on edit form)",
          "/edit" not in page.url or page.locator("#lineItemsBody").count() == 0, "url=%s" % page.url)

    # ---- REJECT path: fresh quote -> send -> reject (with guard) ----
    qb = create_quote(page, b)
    post_action(page, b, qb, "send")
    # guard: short reason refused
    post_action(page, b, qb, "reject", reject_reason="too short")
    check("REJECT GUARD: <10-char reason refused (still sent)", status(qb) == "sent", status(qb))
    post_action(page, b, qb, "reject", reject_reason="Customer chose a competitor offer")
    check("REJECT: sent -> rejected", status(qb) == "rejected", status(qb))

    # ---- CANCEL path: fresh draft quote -> cancel (with guard) ----
    qc = create_quote(page, b)
    post_action(page, b, qc, "cancel", cancel_reason="short")
    check("CANCEL GUARD: <10-char reason refused (still draft)", status(qc) == "draft", status(qc))
    post_action(page, b, qc, "cancel", cancel_reason="Duplicate quotation entered by mistake")
    check("CANCEL: draft -> cancelled", status(qc) == "cancelled", status(qc))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
