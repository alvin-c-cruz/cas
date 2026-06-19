---
name: run-tests
description: Use when the user types /run-tests or asks to run the test suite / pytest and see the results — pass/fail counts, which tests failed, and coverage. Runs the full suite (coverage on, per pytest.ini) and reports raw results.
---

# /run-tests — Run the Full Test Suite

Runs the entire pytest suite and reports the raw results. Use this to answer
"did anything break?" after a change. Pairs with `/guard` (targeted, blast-radius
regression check) — `/run-tests` is the full, unfiltered run.

Optional argument: a pytest path or `-k`/`-m` expression to narrow the run
(e.g. `/run-tests tests/integration/test_sales_invoices.py` or `/run-tests -m withholding_tax`).
With no argument, runs everything.

## What "full suite" means here

`pytest.ini` already sets `addopts`: verbose, `--tb=short`, coverage on
(`--cov=app`, HTML report to `htmlcov/`, term-missing), and `-m "not e2e"`.
So a plain `python -m pytest` runs every non-e2e test with coverage. The e2e
browser smokes are opt-in — run them separately with `python -m pytest -m e2e`
if asked.

## Steps

**1. Run the suite.** Output is large (a coverage table per module). Capture the
full log to a file and surface only the tail — never dump the whole log into context:

```bash
python -m pytest 2>&1 | tee /tmp/cas-pytest-full.log | tail -n 45
```

To narrow with an argument, append it: `python -m pytest <arg> 2>&1 | tee ... | tail -n 45`.
A clean full run takes ~4–5 minutes; use a generous timeout (≥600000 ms).

**2. Report raw results.** From the tail, present:
- The final summary line (e.g. `6 failed, 680 passed, 5 deselected in 259.81s`).
- The `short test summary info` block — the names of any failing tests.
- The coverage `TOTAL` line.
- Where to look deeper: full log at `/tmp/cas-pytest-full.log`, HTML coverage at `htmlcov/index.html`.

Do **not** diff against the baseline or filter known failures (that's `/guard`'s job) —
this skill reports results as-is. If the user wants new-vs-known triage, point them to `/guard`.

## Notes
- Known-baseline failures on `main` (so they're not alarming in a raw run): the 3
  Playwright smoke tests in `tests/smoke/test_accounts_payable_form.py`, plus
  `test_auth_audit`, `test_branch_assignment`, and `test_under_development` logic
  tests. See `memory/project-preexisting-test-failures.md` for the live list.
- A single failing test can be re-run verbosely:
  `python -m pytest tests/path::TestClass::test_name -v`.
