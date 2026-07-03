# WHT Per-Rate Posting Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AP and CDV posting credit each line's withholding tax to the **account configured on that line's ATC** (`WithholdingTax.payable_account`), instead of lumping the whole document's WHT into the hardcoded `20301` — so WHT payable is tracked per rate in the GL.

**Architecture:** Add a WHT-payable-bucketing helper to each of AP and CDV that groups the document's withholding by each line's `withholding_tax.payable_account` (falling back to the current `20301` account when an ATC has none), exactly mirroring the existing input-VAT bucketers (`_input_vat_buckets` / `_cdv_input_vat_buckets`). Replace the single consolidated WHT line in the JE builders with one line per bucket. Data-only feature: no model/migration change; the fields already exist and are populated.

**Tech Stack:** Python 3.13, Flask + SQLAlchemy, Decimal money math, pytest.

## Global Constraints

- **Bucket WHT by `item.withholding_tax.payable_account`.** When the line's ATC has no `payable_account` (None), fall back to the document's existing WHT account (`accts['wt']`, code `20301`). Never drop a line's WHT.
- **Total is invariant.** The sum of the emitted WHT lines must equal the document's `withholding_tax_amount` byte-for-byte — only the *account distribution* changes. The document-level WHT override difference (document `withholding_tax_amount` minus the summed line `wt_amount`s) is applied to the **largest bucket**, exactly as `_input_vat_buckets` does for the VAT override.
- **Order & filter:** buckets sorted by `account.code`; drop any zero bucket.
- **Scope: AP + CDV only** (the withholding-agent / *payable* side). CRV and SI are the *receivable* side (creditable WHT → single account `10212`, no per-rate) and are **out of scope** — do not touch them.
- **CDV is sign-aware:** it credits WHT when positive and debits when negative (mirroring its current consolidated line); apply that per bucket. AP WHT is always a credit.
- **`normal_balance` / VAT / totals math is untouched.** This only changes which payable account WHT credits land in.
- Tests: run from `projects/cas/`; new test files are versioned (`tests/` is tracked). Use `--no-cov` for focused runs. Never weaken a guard to pass a test.

---

### Task 1: AP — `_wht_payable_buckets` + wire into `_post_ap_je`

**Files:**
- Modify: `app/accounts_payable/views.py` (add `_wht_payable_buckets`; replace the consolidated WHT line in `_post_ap_je`)
- Test: `tests/integration/test_ap_wht_buckets.py`

**Interfaces:**
- Consumes: `AccountsPayable.line_items` (each `AccountsPayableItem` has `.withholding_tax` → `WithholdingTax` with `.payable_account`, and `.wt_amount: Decimal`); `AccountsPayable.withholding_tax_amount: Decimal`; the existing `accts['wt']` (Account code `20301`) as fallback.
- Produces: `_wht_payable_buckets(ap, fallback_acct) -> list[tuple[Account, Decimal]]` — ordered by account code, total == `ap.withholding_tax_amount`, override diff on the largest bucket.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_ap_wht_buckets.py
import pytest
from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.withholding_tax.models import WithholdingTax
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.accounts_payable.views import _wht_payable_buckets

pytestmark = [pytest.mark.integration]


def _acct(code, name):
    a = Account(code=code, name=name, account_type='Liability', classification='Current',
                normal_balance='credit', is_active=True)
    db.session.add(a); db.session.flush()
    return a


def _wht(code, rate, payable_acct):
    w = WithholdingTax(code=code, name=code, rate=Decimal(str(rate)), is_active=True,
                       payable_account_id=(payable_acct.id if payable_acct else None))
    db.session.add(w); db.session.flush()
    return w


def _bill_with_lines(lines, wt_total):
    # lines = [(WithholdingTax, wt_amount)]
    ap = AccountsPayable(subtotal=Decimal('0.00'), vat_amount=Decimal('0.00'),
                         withholding_tax_amount=Decimal(str(wt_total)), total_amount=Decimal('0.00'))
    db.session.add(ap); db.session.flush()
    for i, (w, amt) in enumerate(lines, 1):
        it = AccountsPayableItem(accounts_payable_id=ap.id, line_number=i,
                                 amount=Decimal('0.00'), wt_id=(w.id if w else None),
                                 wt_amount=Decimal(str(amt)))
        db.session.add(it)
    db.session.flush()
    return ap


def test_buckets_split_by_rate_account(db_session):
    fallback = _acct('20301', 'Withholding Tax Payable - Expanded')
    a1 = _acct('22105-1', 'WHT Payable - 1%')
    a2 = _acct('22105-2', 'WHT Payable - 2%')
    w1 = _wht('WC158', 1, a1)
    w2 = _wht('WC160', 2, a2)
    ap = _bill_with_lines([(w1, '100.00'), (w2, '200.00'), (w1, '50.00')], wt_total='350.00')

    buckets = _wht_payable_buckets(ap, fallback)
    by_code = {acct.code: amt for acct, amt in buckets}
    assert by_code == {'22105-1': Decimal('150.00'), '22105-2': Decimal('200.00')}
    assert sum(amt for _, amt in buckets) == Decimal('350.00')   # total invariant


def test_buckets_fall_back_when_atc_has_no_payable(db_session):
    fallback = _acct('20301', 'Withholding Tax Payable - Expanded')
    w = _wht('WCX', 5, None)   # no payable account
    ap = _bill_with_lines([(w, '75.00')], wt_total='75.00')
    buckets = _wht_payable_buckets(ap, fallback)
    assert [(a.code, amt) for a, amt in buckets] == [('20301', Decimal('75.00'))]


def test_override_diff_applied_to_largest_bucket(db_session):
    fallback = _acct('20301', 'WHT Payable')
    a1 = _acct('22105-1', 'WHT 1%'); a2 = _acct('22105-2', 'WHT 2%')
    w1 = _wht('WC158', 1, a1); w2 = _wht('WC160', 2, a2)
    # lines sum to 300 but the bill's WHT was overridden to 310 -> +10 to the largest (a2=200)
    ap = _bill_with_lines([(w1, '100.00'), (w2, '200.00')], wt_total='310.00')
    by_code = {a.code: amt for a, amt in _wht_payable_buckets(ap, fallback)}
    assert by_code == {'22105-1': Decimal('100.00'), '22105-2': Decimal('210.00')}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_ap_wht_buckets.py -m integration --no-cov -q`
Expected: FAIL — `ImportError: cannot import name '_wht_payable_buckets'`

- [ ] **Step 3: Add the helper** (place next to `_input_vat_buckets` in `app/accounts_payable/views.py`)

```python
def _wht_payable_buckets(ap, fallback_acct):
    """Group the bill's WHT by each line's ATC payable_account (fallback_acct when the ATC
    has none). Ordered by account code; the bill-level WHT override difference is applied to
    the largest bucket. Total equals ap.withholding_tax_amount. Mirrors _input_vat_buckets."""
    total_wt = Decimal(str(ap.withholding_tax_amount))
    if total_wt <= 0:
        return []
    buckets = {}  # account_id -> [Account, Decimal]
    for item in ap.line_items:
        wt = Decimal(str(item.wt_amount or 0))
        if wt <= 0:
            continue
        wtx = item.withholding_tax
        acct = (wtx.payable_account if wtx and wtx.payable_account else fallback_acct)
        if acct is None:
            continue
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += wt
    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    diff = total_wt - sum((amt for _, amt in ordered), Decimal('0.00'))
    if diff != Decimal('0.00') and ordered:
        largest_id = max(ordered, key=lambda b: b[1])[0].id
        ordered = [(a, amt + diff if a.id == largest_id else amt) for a, amt in ordered]
    return [(a, amt) for a, amt in ordered if amt != Decimal('0.00')]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_ap_wht_buckets.py -m integration --no-cov -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire it into the JE builder.** In `app/accounts_payable/views.py`, inside `_post_ap_je` (and any preview builder that duplicates it), find the consolidated WHT block:

```python
    wt_amount = Decimal(str(ap.withholding_tax_amount))
    if wt_amount > 0 and accts['wt']:
        entries.append({
            'code': accts['wt'].code,
            'name': accts['wt'].name,
            'debit': Decimal('0.00'),
            'credit': wt_amount,
        })
```

and replace it with:

```python
    for wt_acct, wt_amt in _wht_payable_buckets(ap, accts['wt']):
        entries.append({
            'code': wt_acct.code,
            'name': wt_acct.name,
            'debit': Decimal('0.00'),
            'credit': wt_amt,
        })
```

- [ ] **Step 6: Verify existing AP posting tests still pass** (WHT total, balance, and JE unchanged when every ATC lacks a payable account = single `20301` line as before)

Run: `venv/Scripts/python.exe -m pytest tests/ -m accounts_payable --no-cov -q -k "je or post or journal or wht"`
Expected: PASS (no regressions; a single-account bill still yields one `20301` WHT line)

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_ap_wht_buckets.py app/accounts_payable/views.py
git commit -m "feat(ap): route WHT payable per line ATC account (bucket by rate, 20301 fallback)"
```

---

### Task 2: CDV — `_cdv_wht_payable_buckets` + wire into JE builder & preview (sign-aware)

**Files:**
- Modify: `app/cash_disbursements/views.py` (add `_cdv_wht_payable_buckets`; replace the consolidated WHT line in `_post_cdv_je` **and** in `_build_cdv_je_preview`)
- Test: `tests/integration/test_cdv_wht_buckets.py`

**Interfaces:**
- Consumes: `CashDisbursementVoucher.expense_lines` (each `CDVExpenseLine` has `.withholding_tax` → `WithholdingTax.payable_account` and `.wt_amount: Decimal`); the document's total WHT; the existing `accts['wt']` (Account `20301`) fallback.
- Produces: `_cdv_wht_payable_buckets(cdv, fallback_acct) -> list[tuple[Account, Decimal]]` — **signed** amounts (positive = credit, negative = debit), ordered by account code, total equals the document WHT.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_cdv_wht_buckets.py
import pytest
from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.withholding_tax.models import WithholdingTax
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
from app.cash_disbursements.views import _cdv_wht_payable_buckets

pytestmark = [pytest.mark.integration]


def _acct(code, name):
    a = Account(code=code, name=name, account_type='Liability', classification='Current',
                normal_balance='credit', is_active=True)
    db.session.add(a); db.session.flush()
    return a


def _wht(code, rate, payable_acct):
    w = WithholdingTax(code=code, name=code, rate=Decimal(str(rate)), is_active=True,
                       payable_account_id=(payable_acct.id if payable_acct else None))
    db.session.add(w); db.session.flush()
    return w


def _cdv_with_expense_lines(lines):
    cdv = CashDisbursementVoucher()
    db.session.add(cdv); db.session.flush()
    for i, (w, amt) in enumerate(lines, 1):
        el = CDVExpenseLine(cdv_id=cdv.id, line_number=i, amount=Decimal('0.00'),
                            wt_id=(w.id if w else None), wt_amount=Decimal(str(amt)))
        db.session.add(el)
    db.session.flush()
    return cdv


def test_cdv_buckets_split_by_rate_account(db_session):
    fb = _acct('20301', 'WHT Payable')
    a1 = _acct('22105-1', 'WHT 1%'); a2 = _acct('22105-2', 'WHT 2%')
    w1 = _wht('WC158', 1, a1); w2 = _wht('WC160', 2, a2)
    cdv = _cdv_with_expense_lines([(w1, '100.00'), (w2, '200.00')])
    by_code = {a.code: amt for a, amt in _cdv_wht_payable_buckets(cdv, fb)}
    assert by_code == {'22105-1': Decimal('100.00'), '22105-2': Decimal('200.00')}


def test_cdv_buckets_fall_back(db_session):
    fb = _acct('20301', 'WHT Payable')
    w = _wht('WCX', 5, None)
    cdv = _cdv_with_expense_lines([(w, '40.00')])
    assert [(a.code, amt) for a, amt in _cdv_wht_payable_buckets(cdv, fb)] == [('20301', Decimal('40.00'))]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_cdv_wht_buckets.py -m integration --no-cov -q`
Expected: FAIL — `ImportError: cannot import name '_cdv_wht_payable_buckets'`

- [ ] **Step 3: Add the helper** (next to `_cdv_input_vat_buckets` in `app/cash_disbursements/views.py`). Note: `total_wt` is the signed sum of the expense-line `wt_amount`s (CDV has no separate stored bill-level WHT column; use the summed lines).

```python
def _cdv_wht_payable_buckets(cdv, fallback_acct):
    """Group the voucher's WHT by each expense line's ATC payable_account (fallback_acct when
    the ATC has none). Returns SIGNED amounts (positive credit, negative debit), ordered by
    account code. Mirrors _cdv_input_vat_buckets; total equals the summed line WHT."""
    buckets = {}  # account_id -> [Account, Decimal]
    for el in cdv.expense_lines:
        wt = Decimal(str(el.wt_amount or 0))
        if wt == 0:
            continue
        wtx = el.withholding_tax
        acct = (wtx.payable_account if wtx and wtx.payable_account else fallback_acct)
        if acct is None:
            continue
        if acct.id not in buckets:
            buckets[acct.id] = [acct, Decimal('0.00')]
        buckets[acct.id][1] += wt
    ordered = [(b[0], b[1]) for b in sorted(buckets.values(), key=lambda b: b[0].code)]
    return [(a, amt) for a, amt in ordered if amt != Decimal('0.00')]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_cdv_wht_buckets.py -m integration --no-cov -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire it into both the JE builder and the preview.** In `app/cash_disbursements/views.py`, in **`_post_cdv_je`** and again in **`_build_cdv_je_preview`**, find the consolidated sign-aware WHT block (it computes `total_wt` from the expense lines and appends one credit-or-debit line to `accts['wt']`):

```python
    total_wt = sum((Decimal(str(el.wt_amount or 0)) for el in cdv.expense_lines), Decimal('0.00'))
    if total_wt != Decimal('0.00') and accts['wt']:
        if total_wt > 0:
            entries.append({'code': accts['wt'].code, 'name': accts['wt'].name,
                            'debit': Decimal('0.00'), 'credit': total_wt})
        else:
            entries.append({'code': accts['wt'].code, 'name': accts['wt'].name,
                            'debit': -total_wt, 'credit': Decimal('0.00')})
```

and replace each with a per-bucket version:

```python
    for wt_acct, wt_amt in _cdv_wht_payable_buckets(cdv, accts['wt']):
        if wt_amt > 0:
            entries.append({'code': wt_acct.code, 'name': wt_acct.name,
                            'debit': Decimal('0.00'), 'credit': wt_amt})
        else:
            entries.append({'code': wt_acct.code, 'name': wt_acct.name,
                            'debit': -wt_amt, 'credit': Decimal('0.00')})
```

(The exact surrounding lines may differ slightly between `_post_cdv_je` and `_build_cdv_je_preview`; match each site's existing single-line WHT logic and swap in the loop. Keep the sign convention identical to what was there.)

- [ ] **Step 6: Verify existing CDV posting + preview tests still pass**

Run: `venv/Scripts/python.exe -m pytest tests/ -m cash_disbursements --no-cov -q -k "je or post or preview or wht or entry"`
Expected: PASS (single-account voucher yields one `20301` WHT line as before; preview and posted JE agree)

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_cdv_wht_buckets.py app/cash_disbursements/views.py
git commit -m "feat(cdv): route WHT payable per line ATC account (bucket by rate, 20301 fallback, sign-aware)"
```

---

## Self-Review

**Spec coverage:** bucket by ATC payable_account (Tasks 1 & 2 helpers), `20301` fallback (fall-back tests), total invariance + override-diff-to-largest (Task 1 override test; CDV has no separate override column so it sums lines), sort/filter (helper), AP+CDV only / CRV+SI untouched (scope note; no CRV/SI files modified), CDV sign-awareness (Task 2 wiring), math otherwise unchanged (Step 6 regression runs each task). ✔

**Placeholder scan:** every step has complete code; Task 2 Step 5 notes the two sites may differ slightly and says exactly how to reconcile (match existing sign logic, swap the single line for the loop) — that is guidance for a real ambiguity, not a placeholder. The regression `-k` filters are best-effort selectors; if a task's run collects 0 tests, widen to the full module marker (`-m accounts_payable` / `-m cash_disbursements`). ✔

**Type consistency:** both helpers return `list[tuple[Account, Decimal]]`; AP amounts are always positive (credit), CDV amounts are signed and the caller emits credit/debit — documented in both Interfaces blocks and matched in the wiring steps. `withholding_tax.payable_account` / `.wt_amount` / `line_items` / `expense_lines` match the real models. ✔
