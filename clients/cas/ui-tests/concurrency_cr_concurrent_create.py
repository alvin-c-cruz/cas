"""Concurrency stress test: N=3 same-role (uitest_ca) sessions independently CREATE a NEW
Cash Receipt voucher (standalone revenue, no AR collection) at (near) the same instant --
extends the JV/SI/AP/CD concurrency probes to CR, the last of the Core 5 documents.

Code review confirmed the SAME vulnerable shape: `generate_crv_number()`
(`app/cash_receipts/views.py:75`) is called once at GET (line 946); the POST DOES have a
pre-check (`CashReceiptVoucher.query.filter_by(crv_number=form.crv_number.data).first()`, line
881) giving a friendly error ("CR Number ... already exists") -- same check-then-act shape as
AP/CD, not atomic with the insert. `crv_number` carries `unique=True`
(`app/cash_receipts/models.py:15`).

Same technique as the earlier probes: Playwright opens N independent contexts (real logins),
captures cookies/CSRF/pre-generated number, then fires the actual collision via `requests` +
`threading.Barrier` (thread-safe; sync Playwright is not).

Requires the CAS-scope shared setup (`_shared_setup_cas_scope.py`, `_register_ca.py`) for
account 1610 (stand-in cash/bank account) and account 4110 (revenue), plus Customer CASCUST1.
"""
import sys, sqlite3, threading, json
from datetime import date
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\envs\erp-workspace\.claude\skills\ui-test")
from playwright.sync_api import sync_playwright
import harness
import requests

DB = r"C:\envs\erp-workspace\projects\cas\instance\_uitest-cas.db"
N = 3
USER = "uitest_ca"
TAG = "concurrency-cr-create"

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

    cash_id = q1("SELECT id FROM accounts WHERE code='1610'")[0]
    revenue_id = q1("SELECT id FROM accounts WHERE code='4110'")[0]
    cust_id = q1("SELECT id FROM customers WHERE code='CASCUST1'")[0]

    print(f"=== opening {N} independent uitest_ca sessions, each loading the CR create form ===")
    sessions = []
    contexts = []
    for i in range(N):
        browser, ctx, sess, number, csrf = open_session(
            pw, s["cdp_url"], base, USER, pw_password, "/cash-receipts/create", "crv_number")
        contexts.append((browser, ctx))
        sessions.append({"session": sess, "number": number, "csrf": csrf, "desc": f"{TAG}-{i+1}"})
        print(f"  user {i+1}: pre-fetched crv_number={number!r}")

    distinct_prefetched = len({info["number"] for info in sessions})
    print(f"  distinct crv_numbers pre-fetched across {N} sessions: {distinct_prefetched}")

    barrier = threading.Barrier(N)
    responses = [None] * N

    def worker(idx):
        info = sessions[idx]
        lines = [{"account_id": revenue_id, "description": info["desc"], "amount": "100.00"}]
        data = {
            "csrf_token": info["csrf"],
            "crv_number": info["number"],
            "crv_date": date.today().isoformat(),
            "customer_id": str(cust_id),
            "payment_method": "cash",
            "cash_account_id": str(cash_id),
            "notes": info["desc"],
            "ar_lines": "[]",
            "revenue_lines": json.dumps(lines),
        }
        barrier.wait()
        responses[idx] = info["session"].post(base + "/cash-receipts/create", data=data, allow_redirects=False)

    print(f"=== firing all {N} creates through a barrier (near-simultaneous POST) ===")
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, r in enumerate(responses):
        loc = r.headers.get("Location", "") if r is not None else ""
        print(f"  user {i+1} POST -> status={r.status_code if r is not None else 'ERR'} location={loc}")

    rows = q(f"SELECT crv_number, notes FROM cash_receipt_vouchers WHERE notes LIKE '{TAG}-%' ORDER BY id")
    print("  DB rows committed:", rows)
    numbers = [row[0] for row in rows]
    committed = len(rows)

    check("no duplicate crv_number ever committed (DB unique constraint integrity)",
          len(numbers) == len(set(numbers)), str(numbers))
    check(f"all {N} concurrent creates committed (no data loss under the race)",
          committed == N,
          f"{committed}/{N} committed, {distinct_prefetched}/{N} distinct numbers pre-fetched -- rows={rows}")

    if committed < N:
        print(f"\n  >>> CONFIRMS the pre-check ({N - committed} of {N} lost) does NOT close the race in CR either.")

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok:
            print("  FAILED:", n, "--", d)
