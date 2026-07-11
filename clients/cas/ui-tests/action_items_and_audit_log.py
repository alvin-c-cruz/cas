"""Action Items sidebar badge + Audit Log trail test (as admin).

Badge (count_action_items) = countable drafts + pending master-data approvals. We drive
the pending-approval path: create a COA account (-> pending) increments the badge; approve
and reject each decrement it. Then verify the audit log recorded the CRUD trail + filters.
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

def badge(page, b):
    """Read the live sidebar Action Items badge (0 when hidden)."""
    page.goto(b + "/dashboard", wait_until="networkidle")
    el = page.locator("#nav-action-badge")
    return int(el.inner_text().strip()) if el.count() and el.is_visible() else 0

def reenable(page):
    page.eval_on_selector_all("input,select,textarea","els=>els.forEach(e=>{e.removeAttribute('readonly');e.removeAttribute('disabled');})")

def create_account(page, b, code, name):
    page.goto(b + "/accounts/create", wait_until="networkidle"); reenable(page)
    page.fill("input[name='code']", code); page.fill("input[name='name']", name)
    page.select_option("select[name='account_type']", "Asset")
    page.select_option("select[name='classification']", "Current")
    reenable(page)
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("()=>document.querySelector(\"input[name='code']\").form.submit()")

def latest_pending_req():
    r = q1("SELECT id FROM account_change_requests WHERE status='pending' ORDER BY id DESC LIMIT 1")
    return r[0] if r else None

def review(page, b, rid, action):  # action in {approve, reject}
    page.goto(b + "/accounts/pending-approvals", wait_until="networkidle")
    with page.expect_navigation(wait_until="networkidle"):
        page.evaluate("""(a)=>{const[rid,act]=a;const f=document.getElementById(act+'-form');
            f.action='/accounts/'+act+'/'+rid;
            if(act==='reject'){const t=document.createElement('input');t.type='hidden';t.name='rejection_reason';t.value='not needed';f.appendChild(t);}
            f.submit();}""", [rid, action])

with sync_playwright() as pw:
    browser, page = harness.connect(pw, slow_mo=170)
    b = harness.base_url(); harness.login(page, "admin")

    # ===== Action Items badge =====
    # idempotent: pick two account codes that don't exist yet (re-runnable on a persistent DB)
    used = {r[0] for r in sqlite3.connect(DB).execute("SELECT code FROM accounts WHERE code LIKE '99%'")}
    free = [c for c in ("9990","9991","9992","9993","9994","9995","9996","9997","9998","9999") if c not in used]
    codeA, codeB = free[0], free[1]

    base = badge(page, b)
    check("badge baseline read", True, "baseline=%d" % base)

    create_account(page, b, codeA, "Action Items Test %s" % codeA)
    check("badge +1 after a pending COA request", badge(page, b) == base + 1, "now=%d" % badge(page, b))

    review(page, b, latest_pending_req(), "approve")
    check("badge -1 after APPROVE", badge(page, b) == base, "now=%d" % badge(page, b))

    create_account(page, b, codeB, "Action Items Test %s" % codeB)
    mid = badge(page, b)
    check("badge +1 again (2nd pending)", mid == base + 1, "now=%d" % mid)
    review(page, b, latest_pending_req(), "reject")
    check("badge -1 after REJECT", badge(page, b) == base, "now=%d" % badge(page, b))

    # ===== Audit Log trail (renders as .audit-entry cards, not a table) =====
    page.goto(b + "/audit-log", wait_until="networkidle")
    check("audit-log page renders for admin (entry cards present)",
          "audit" in page.url and page.locator(".audit-entry").count() > 0,
          "entries=%d" % page.locator(".audit-entry").count())

    # DB-level: our session generated audit entries across modules
    mods = dict(sqlite3.connect(DB).execute(
        "SELECT module, COUNT(*) FROM audit_logs GROUP BY module").fetchall())
    print("   audit modules:", mods)
    check("audit recorded account create/approve", mods.get("account", 0) >= 2, str(mods.get("account")))
    check("audit recorded master-data creates (customer+products)",
          mods.get("customer", 0) >= 1 and mods.get("products", 0) >= 1,
          "cust=%s products=%s" % (mods.get("customer"), mods.get("products")))
    check("audit recorded Sales-Area docs (quotations, sales_orders, delivery_receipts)",
          all(mods.get(m, 0) >= 1 for m in ("quotations", "sales_orders", "delivery_receipts")),
          "q=%s so=%s dr=%s" % (mods.get("quotations"), mods.get("sales_orders"), mods.get("delivery_receipts")))

    # reject logs action='reject' (not the original change type)
    rej = q1("SELECT COUNT(*) FROM audit_logs WHERE module='account' AND action='reject'")[0]
    check("reject logged as action='reject'", rej >= 1, "reject rows=%d" % rej)

    # actor recorded (admin) on account creates
    who = q1("SELECT u.username FROM audit_logs a JOIN users u ON u.id=a.user_id WHERE a.module='account' AND a.action='create' ORDER BY a.id DESC LIMIT 1")
    check("audit entry carries the actor (admin)", who and who[0] == "admin", str(who))

    # UI module filter narrows the card list (account has many; products few)
    page.goto(b + "/audit-log?module=account", wait_until="networkidle")
    rows_acct = page.locator(".audit-entry").count()
    page.goto(b + "/audit-log?module=products", wait_until="networkidle")
    rows_prod = page.locator(".audit-entry").count()
    check("audit-log module filter narrows (account entries != products entries, both > 0)",
          rows_acct > 0 and rows_prod > 0 and rows_acct != rows_prod,
          "account=%d products=%d" % (rows_acct, rows_prod))

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok: print("  FAILED:", n, "--", d)
