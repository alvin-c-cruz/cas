"""Concurrency stress test: N=3 same-role (uitest_ca) sessions independently CREATE a NEW
Sales Invoice at (near) the same instant -- extends `concurrency_jv_concurrent_create.py`'s
technique to Sales Invoice, per the owner's request to check how widespread JV's number-race
pattern is.

Code review confirmed the SAME vulnerable shape as JV: `generate_invoice_number()`
(`app/sales_invoices/views.py:89`) is called once, on the GET that renders the create form
(line 785), and the POST (line 729) persists whatever `invoice_number` the form carries
verbatim -- no re-check, no lock. `invoice_number` carries `unique=True`
(`app/sales_invoices/models.py:40`). Unlike CD/CR, SI has NO pre-check for a duplicate before
insert -- it relies purely on the DB constraint + a blanket `except Exception` (line 777) that
flashes `f'Error entering Sales Invoice: {str(e)}'` (includes the raw exception text, arguably
worse UX than JV's fully-generic message). Same technique as the JV probe: Playwright opens N
independent contexts (real logins), captures cookies/CSRF/pre-generated number, then fires the
actual collision via `requests` + `threading.Barrier` (thread-safe; sync Playwright is not).

Requires the CAS-scope shared setup (`_shared_setup_cas_scope.py`, `_register_ca.py`) for
account 4110, VAT category V12, WHT WC010, Customer CASCUST1, and the uitest_ca user.
"""
import sys, sqlite3, threading, json
from datetime import date, timedelta
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness
import requests

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
N = 3
USER = "uitest_ca"
TAG = "concurrency-si-create"

results = []
def check(n, ok, d=""):
    results.append((bool(ok), n, d)); print(("PASS " if ok else "FAIL ") + n + (("  -- " + d) if d else ""))
def q(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchall()
def q1(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchone()


def open_session(pw, cdp_url, base, username, password, create_url, number_field_id):
    browser = pw.chromium.connect_over_cdp(cdp_url)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(base + "/logout", wait_until="networkidle")
    page.goto(base + "/login", wait_until="networkidle")
    harness.strip_readonly(page, "#username, #password")
    page.fill("#username", username)
    page.fill("#password", password)
    page.press("#password", "Enter")
    page.wait_for_load_state("networkidle")

    page.goto(base + create_url, wait_until="networkidle")
    number = page.eval_on_selector(f"#{number_field_id}", "el => el.value")
    csrf = page.eval_on_selector("input[name='csrf_token']", "el => el.value")

    sess = requests.Session()
    for c in ctx.cookies():
        sess.cookies.set(c["name"], c["value"], domain=c["domain"])
    return browser, ctx, sess, number, csrf


with sync_playwright() as pw:
    s = harness.state()
    base = s["base_url"]
    pw_password = harness.password()

    sales_id = q1("SELECT id FROM accounts WHERE code='4110'")[0]
    cust_id = q1("SELECT id FROM customers WHERE code='CASCUST1'")[0]
    wht_id = q1("SELECT id FROM withholding_tax WHERE code='WC010'")[0]

    print(f"=== opening {N} independent uitest_ca sessions, each loading the SI create form ===")
    sessions = []
    contexts = []
    for i in range(N):
        browser, ctx, sess, number, csrf = open_session(
            pw, s["cdp_url"], base, USER, pw_password, "/sales-invoices/create", "invoice_number")
        contexts.append((browser, ctx))
        sessions.append({"session": sess, "number": number, "csrf": csrf, "desc": f"{TAG}-{i+1}"})
        print(f"  user {i+1}: pre-fetched invoice_number={number!r}")

    # Scope this run's own rows by the number pre-fetched at open time -- guaranteed
    # unique per invocation (the DB is persistent across repeated runs of this spec).
    run_id = sessions[0]["number"]
    for info in sessions:
        info["desc"] = f"{info['desc']}-{run_id}"

    distinct_prefetched = len({info["number"] for info in sessions})
    print(f"  distinct invoice_numbers pre-fetched across {N} sessions: {distinct_prefetched}")

    barrier = threading.Barrier(N)
    responses = [None] * N

    def worker(idx):
        info = sessions[idx]
        lines = [{"account_id": sales_id, "description": info["desc"], "amount": "1120.00",
                  "vat_category": "V12", "wt_id": wht_id}]
        today = date.today()
        data = {
            "csrf_token": info["csrf"],
            "invoice_number": info["number"],
            "invoice_date": today.isoformat(),
            "due_date": (today + timedelta(days=30)).isoformat(),
            "customer_id": str(cust_id),
            "payment_terms": "Net 30",
            "notes": info["desc"],
            "line_items": json.dumps(lines),
        }
        barrier.wait()
        responses[idx] = info["session"].post(base + "/sales-invoices/create", data=data, allow_redirects=False)

    print(f"=== firing all {N} creates through a barrier (near-simultaneous POST) ===")
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, r in enumerate(responses):
        loc = r.headers.get("Location", "") if r is not None else ""
        print(f"  user {i+1} POST -> status={r.status_code if r is not None else 'ERR'} location={loc}")

    rows = q(f"SELECT invoice_number, notes FROM sales_invoices WHERE notes LIKE '%-{run_id}' ORDER BY id")
    print("  DB rows committed:", rows)
    numbers = [row[0] for row in rows]
    committed = len(rows)

    check("no duplicate invoice_number ever committed (DB unique constraint integrity)",
          len(numbers) == len(set(numbers)), str(numbers))
    check("at least 1 of the concurrent creates committed", committed >= 1,
          f"{committed}/{N} committed -- rows={rows}")

    # FIXED 2026-07-12: SI is a "surfaced" fix (fresh_number_if_collision + the
    # flush_or_suggest_fresh_number backstop) -- unlike JV's silent retry, only the
    # winner commits; every OTHER concurrent request must get a clean re-render with a
    # fresh distinct number, never the raw sqlite3.IntegrityError this bug used to leak.
    losers_ok = True
    loser_details = []
    for i, r in enumerate(responses):
        if r is not None and r.status_code == 200:
            has_raw_error = "IntegrityError" in r.text
            has_friendly = "suggested below" in r.text.lower()
            loser_details.append(f"user{i+1}: friendly={has_friendly} raw_error={has_raw_error}")
            if has_raw_error or not has_friendly:
                losers_ok = False
    check("every non-committing response got the friendly fresh-number re-render, not a raw exception",
          losers_ok, "; ".join(loser_details) if loser_details else "no losers this run (unlikely, but not a failure)")

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok:
            print("  FAILED:", n, "--", d)
