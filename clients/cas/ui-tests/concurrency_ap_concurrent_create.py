"""Concurrency stress test: N=3 same-role (uitest_ca) sessions independently CREATE a NEW
Accounts Payable voucher at (near) the same instant -- extends the JV/SI concurrency probes to
AP, per the owner's request to check how widespread the number-race pattern is.

Code review confirmed the SAME vulnerable shape: `generate_ap_number()`
(`app/accounts_payable/views.py:1679`) is called once at GET (line 841); the POST DOES have a
pre-check (`AccountsPayable.query.filter(AccountsPayable.ap_number == ap_num).first()`, line 744)
that gives a friendly, specific error ("AP number ... is already in use") -- but the check and the
insert are not in the same atomic transaction, so it is still a check-then-act race, not a fix.
`ap_number` carries `unique=True` (`app/accounts_payable/models.py:39`).

Same technique as the JV/SI probes: Playwright opens N independent contexts (real logins),
captures cookies/CSRF/pre-generated number, then fires the actual collision via `requests` +
`threading.Barrier` (thread-safe; sync Playwright is not).

Requires the CAS-scope shared setup (`_shared_setup_cas_scope.py`, `_register_ca.py`) for a leaf
expense account (1720), and Vendor CASVEND1.
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
TAG = "concurrency-ap-create"

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

    expense_id = q1("SELECT id FROM accounts WHERE code='1720'")[0]
    vendor_id = q1("SELECT id FROM vendors WHERE code='CASVEND1'")[0]

    print(f"=== opening {N} independent uitest_ca sessions, each loading the AP create form ===")
    sessions = []
    contexts = []
    for i in range(N):
        browser, ctx, sess, number, csrf = open_session(
            pw, s["cdp_url"], base, USER, pw_password, "/accounts-payable/create", "ap_number")
        contexts.append((browser, ctx))
        sessions.append({"session": sess, "number": number, "csrf": csrf, "desc": f"{TAG}-{i+1}"})
        print(f"  user {i+1}: pre-fetched ap_number={number!r}")

    # Scope this run's own rows by the number pre-fetched at open time -- guaranteed
    # unique per invocation (the DB is persistent across repeated runs of this spec).
    run_id = sessions[0]["number"]
    for info in sessions:
        info["desc"] = f"{info['desc']}-{run_id}"

    distinct_prefetched = len({info["number"] for info in sessions})
    print(f"  distinct ap_numbers pre-fetched across {N} sessions: {distinct_prefetched}")

    barrier = threading.Barrier(N)
    responses = [None] * N

    def worker(idx):
        info = sessions[idx]
        lines = [{"account_id": expense_id, "description": info["desc"], "amount": "100.00"}]
        today = date.today()
        data = {
            "csrf_token": info["csrf"],
            "ap_number": info["number"],
            "ap_date": today.isoformat(),
            "due_date": (today + timedelta(days=30)).isoformat(),
            "payee": f"vendor:{vendor_id}",
            "payment_terms": "Net 30",
            "notes": info["desc"],
            "line_items": json.dumps(lines),
        }
        barrier.wait()
        responses[idx] = info["session"].post(base + "/accounts-payable/create", data=data, allow_redirects=False)

    print(f"=== firing all {N} creates through a barrier (near-simultaneous POST) ===")
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, r in enumerate(responses):
        loc = r.headers.get("Location", "") if r is not None else ""
        print(f"  user {i+1} POST -> status={r.status_code if r is not None else 'ERR'} location={loc}")

    rows = q(f"SELECT ap_number, notes FROM accounts_payable WHERE notes LIKE '%-{run_id}' ORDER BY id")
    print("  DB rows committed:", rows)
    numbers = [row[0] for row in rows]
    committed = len(rows)

    check("no duplicate ap_number ever committed (DB unique constraint integrity)",
          len(numbers) == len(set(numbers)), str(numbers))
    check(f"all {N} concurrent creates committed (no data loss under the race)",
          committed == N,
          f"{committed}/{N} committed, {distinct_prefetched}/{N} distinct numbers pre-fetched -- rows={rows}")

    if committed < N:
        print(f"\n  >>> CONFIRMS the pre-check ({N - committed} of {N} lost) does NOT close the race -- "
              f"it is check-then-act, not atomic with the insert.")

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok:
            print("  FAILED:", n, "--", d)
