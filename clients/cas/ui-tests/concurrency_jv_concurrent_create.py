"""Concurrency regression guard: N=3 same-role (uitest_ca) sessions independently CREATE a NEW
Journal Voucher at (near) the same instant, exercising JournalEntry.entry_number's
generation-at-page-load race.

FIXED 2026-07-12 -- `commit_with_renumber_retry()` (`app/utils/concurrency.py`), wired into
`journal_entries/views.py::create()`. Originally: `generate_jv_number()` is called once on the
GET that renders the create form, and the submitted number is persisted verbatim at POST with
no re-check/lock. `entry_number` carries a DB-level `unique=True`. Two users opening the create
page in the same window both saw the SAME suggested number; whichever POST committed second
used to hit the unique constraint, caught by a blanket `except Exception` -> generic error ->
silent data loss. The fix retries the commit with a freshly generated number (bounded, 3
attempts) instead of failing -- this spec now expects and asserts 2/2 (all N concurrent creates
succeed with distinct numbers). See docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md.

Technique: Playwright's SYNC API is not safe to drive concurrently across threads sharing one
browser/page object, and the shared harness.connect() always reuses ONE context (one login).
So this script uses Playwright only for the (sequential, legitimate) part -- opening N separate
browser contexts, logging in as uitest_ca in each, and loading the create form to capture each
session's real cookies + CSRF token + pre-generated entry_number. The actual timed COLLISION is
then fired via plain `requests.Session` POSTs (thread-safe) released together by a
`threading.Barrier(N)`, so the three submits reach the server within milliseconds of each other
-- a faithful repro of the real race without touching Playwright objects off-thread.

Requires the CAS-scope shared setup (`_shared_setup_cas_scope.py`) for accounts 1610/4110 and
the `uitest_ca` user (`_register_ca.py`).

This is NOT a pass/fail correctness gate in the usual sense -- it's a probe. It asserts the one
invariant that must ALWAYS hold (no duplicate entry_number is ever committed -- the DB
constraint itself guarantees this), then reports how many of the N concurrent submits actually
committed. If fewer than N succeeded, that confirms BUG-JV-NUMBER-RACE-SILENT-DATA-LOSS (logged
in project-bug-tracker) rather than failing the run silently.
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
TAG = "concurrency-jv-create"

results = []
def check(n, ok, d=""):
    results.append((bool(ok), n, d)); print(("PASS " if ok else "FAIL ") + n + (("  -- " + d) if d else ""))
def q(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchall()
def q1(sql, *a): return sqlite3.connect(DB).execute(sql, a).fetchone()


def open_session(pw, cdp_url, base, username, password):
    """Open a fresh, independent browser context (separate cookie jar), log in, and
    load the JV create form -- returns a requests.Session carrying the real cookies,
    plus the page's pre-generated entry_number and CSRF token."""
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

    page.goto(base + "/journal-entries/create", wait_until="networkidle")
    entry_number = page.eval_on_selector("#entry_number", "el => el.value")
    csrf = page.eval_on_selector("input[name='csrf_token']", "el => el.value")

    sess = requests.Session()
    for c in ctx.cookies():
        sess.cookies.set(c["name"], c["value"], domain=c["domain"])
    return browser, ctx, sess, entry_number, csrf


with sync_playwright() as pw:
    s = harness.state()
    base = s["base_url"]
    pw_password = harness.password()

    ar_id = q1("SELECT id FROM accounts WHERE code='1610'")[0]
    sales_id = q1("SELECT id FROM accounts WHERE code='4110'")[0]

    print(f"=== opening {N} independent uitest_ca sessions, each loading the JV create form ===")
    sessions = []
    contexts = []
    for i in range(N):
        browser, ctx, sess, entry_number, csrf = open_session(pw, s["cdp_url"], base, USER, pw_password)
        contexts.append((browser, ctx))
        sessions.append({"session": sess, "entry_number": entry_number, "csrf": csrf, "desc": f"{TAG}-{i+1}"})
        print(f"  user {i+1}: pre-fetched entry_number={entry_number!r}")

    # Scope this run's own rows by the number pre-fetched at open time -- guaranteed
    # unique per invocation (the DB is persistent across repeated runs of this spec, so
    # a fixed TAG alone would pick up stale rows from an earlier run's leftovers).
    run_id = sessions[0]["entry_number"]
    for info in sessions:
        info["desc"] = f"{info['desc']}-{run_id}"

    distinct_numbers_prefetched = len({info["entry_number"] for info in sessions})
    print(f"  distinct entry_numbers pre-fetched across {N} sessions: {distinct_numbers_prefetched}")

    barrier = threading.Barrier(N)
    responses = [None] * N

    def worker(idx):
        info = sessions[idx]
        lines = [
            {"account_id": ar_id, "description": "concurrency debit", "debit": 100.00, "credit": 0},
            {"account_id": sales_id, "description": "concurrency credit", "debit": 0, "credit": 100.00},
        ]
        data = {
            "csrf_token": info["csrf"],
            "entry_number": info["entry_number"],
            "entry_date": date.today().isoformat(),
            "description": info["desc"],
            "reference": "",
            "entry_type": "adjustment",
            "lines": json.dumps(lines),
        }
        barrier.wait()
        responses[idx] = info["session"].post(base + "/journal-entries/create", data=data, allow_redirects=False)

    print(f"=== firing all {N} creates through a barrier (near-simultaneous POST) ===")
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, r in enumerate(responses):
        loc = r.headers.get("Location", "") if r is not None else ""
        print(f"  user {i+1} POST -> status={r.status_code if r is not None else 'ERR'} location={loc}")

    rows = q(f"SELECT entry_number, description FROM journal_entries WHERE description LIKE '%-{run_id}' ORDER BY id")
    print("  DB rows committed:", rows)
    numbers = [row[0] for row in rows]
    committed = len(rows)

    check("no duplicate entry_number ever committed (DB unique constraint integrity)",
          len(numbers) == len(set(numbers)), str(numbers))
    check(f"all {N} concurrent creates committed (no data loss under the race)",
          committed == N,
          f"{committed}/{N} committed, {distinct_numbers_prefetched}/{N} distinct numbers were pre-fetched -- "
          f"rows={rows}, responses={[(r.status_code if r is not None else 'ERR') for r in responses]}")

    if committed < N:
        print(f"\n  >>> CONFIRMS the race: {N - committed} of {N} concurrent JV creates were silently lost "
              f"(generic 'An error occurred' flash, no auto-renumber-and-retry). See BUG-JV-NUMBER-RACE-"
              f"SILENT-DATA-LOSS in project-bug-tracker.")

    print("\n==== SUMMARY ====")
    print(f"{sum(1 for ok,*_ in results if ok)}/{len(results)} checks passed")
    for ok, n, d in results:
        if not ok:
            print("  FAILED:", n, "--", d)
