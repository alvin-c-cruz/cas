# Opening Balances — SI Line-Item Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/opening-balances` line item behave like the Sales Invoice line item — a Choices.js search-select account picker and Debit/Credit fields with onfocus/onblur formatting and Debit-XOR-Credit auto-clear.

**Architecture:** Front-end only. The Flask view/model/migrations are unchanged — the server already strips commas (`_to_decimal`), rejects non-leaf accounts, and rejects both-filled lines. The template gains the shared Choices/transaction assets, a Jinja row macro, and a `<template>` element for building new rows; `opening_balances.js` is rewritten to upgrade each account `<select>` via the shared `initSearchSelect()` and wire the number-field handlers. New rows are built by cloning the server-rendered `<template>` (reuses Jinja's option rendering — no JSON serialization), because Choices.js wraps the `<select>` and the old `cloneNode`-of-a-live-row approach can't survive.

**Tech Stack:** Flask/Jinja templates, vanilla JS, Choices.js (bundled at `app/static/choices.min.js`), shared `app/static/search-select.js` (`initSearchSelect`) and `app/static/transaction-utils.js` (`amtFmt`), pytest + Playwright (`pytest-playwright`) for the e2e smoke.

**Spec:** `docs/superpowers/specs/2026-07-03-opening-balances-si-parity-design.md`

## Global Constraints

- **No server/model/migration changes.** `app/opening_balances/views.py`, models, and Alembic are untouched. (`_to_decimal` already does `.replace(',', '')`; `_parse_lines` already enforces leaf-only + not-both.)
- **No hardcoded styling** — design tokens / CSS variables only (CLAUDE.md).
- **No JS popups** — custom HTML modals only (the finalize modal already complies; keep it).
- **Static-asset cache-buster:** after editing any `app/static/*` file, bump its `?v=N` on every `<link>`/`<script>` that loads it (CLAUDE.md).
- **Dev server does NOT hot-reload Python;** templates and static files DO reload live. No `.py` changes here, so no restart is needed to see changes.
- **Peso sign:** literal `₱` (U+20B1), never `&#8369;`.
- **Account picker list (decided):** keep ALL accounts; group/parent headers appear `disabled` with `'— ' * depth` indent; format `code : name`.
- **Number display (decided):** on focus → plain comma-free number + select-all; on blur → `1,234.56` (en-PH, 2dp) when `> 0`, else **blank**; entering an amount in one of Debit/Credit **clears the sibling** on that row.
- **en-PH money formatting comes from the shared `amtFmt(n)`** in `transaction-utils.js` — do not re-implement it.

---

## File Structure

- `app/opening_balances/templates/opening_balances/form.html` — **modify.** Add Choices/transactions CSS + Choices/search-select/transaction-utils JS; define a Jinja `ob_row` macro; render rows and a `<template id="ob-row-template">` via the macro; add a blank placeholder `<option>`; bump `opening_balances.js` to `?v=3` and `opening_balances.css` to `?v=2`.
- `app/static/js/opening_balances.js` — **rewrite.** Upgrade rows on load, build new rows from the `<template>`, focus/blur formatting, sibling auto-clear, totals recalc, finalize modal.
- `app/static/opening_balances.css` — **modify.** Drop the now-dead native-`<select>` input rule (the account cell hosts a Choices widget styled by `transactions.css`); keep column widths + number-input styling.
- `tests/e2e/test_opening_balances_smoke.py` — **create.** Playwright smoke for search-select + focus/blur + auto-clear + add/remove + save round-trip.
- `tests/integration/test_opening_balances_parse.py` — **create.** Server characterization test: `_parse_lines` accepts comma-formatted amounts.
- `pytest.ini` — **modify.** Register the `opening_balances` marker.
- `.claude/regression-map.json` — **modify.** Add the `opening_balances` module + map the shared files it now depends on.
- `docs/superpowers/plans/INDEX.md` — **modify/create.** Index this plan.

---

## Task 1: Characterization test — `_parse_lines` accepts comma-formatted amounts

Pins the spec's "no server change needed" claim: a submitted `1,234.56` must parse to `Decimal('1234.56')`, and a valid leaf account must be accepted.

**Files:**
- Test: `tests/integration/test_opening_balances_parse.py` (create)

**Interfaces:**
- Consumes: `app.opening_balances.views._parse_lines(form) -> list[dict]` (raises `OpeningLineError`); `app.accounts.models.Account`.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_opening_balances_parse.py
"""The Opening Balances line parser must tolerate comma-formatted amounts, so the
UI can post '1,234.56' without any server change. Also pins leaf-only acceptance."""
import pytest
from decimal import Decimal
from werkzeug.datastructures import MultiDict

from app import db
from app.accounts.models import Account
from app.opening_balances.views import _parse_lines, OpeningLineError

pytestmark = [pytest.mark.integration, pytest.mark.opening_balances]


def _leaf_account():
    """A postable leaf: a top-level parent (group) with one child (leaf)."""
    parent = Account(code='10000', name='Assets Root', account_type='Asset', is_active=True)
    db.session.add(parent)
    db.session.flush()
    leaf = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   parent_id=parent.id, is_active=True)
    db.session.add(leaf)
    db.session.commit()
    return leaf


def test_parse_lines_strips_commas(db_session):
    leaf = _leaf_account()
    form = MultiDict([('account_id', str(leaf.id)), ('debit', '1,234.56'), ('credit', '')])
    rows = _parse_lines(form)
    assert rows == [{'account_id': leaf.id, 'debit': Decimal('1234.56'), 'credit': Decimal('0')}]


def test_parse_lines_rejects_both_filled(db_session):
    leaf = _leaf_account()
    form = MultiDict([('account_id', str(leaf.id)), ('debit', '100.00'), ('credit', '50.00')])
    with pytest.raises(OpeningLineError):
        _parse_lines(form)
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `venv/Scripts/python -m pytest tests/integration/test_opening_balances_parse.py -v -p no:cacheprovider --no-cov`
Expected: PASS (characterization — the server already behaves this way). If `Account(...)` raises on an unknown kwarg, open `app/accounts/models.py`, match its real column names (e.g. `account_type` vs `type`), and fix the test only. Re-run until green.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_opening_balances_parse.py
git commit -m "test(opening-balances): pin _parse_lines comma tolerance + not-both guard"
```

---

## Task 2: Template — shared assets, `ob_row` macro, and row `<template>`

Adds the Choices/transaction assets and refactors the row markup into one Jinja macro used by the entry rows, the starter row, and a hidden `<template>` that JS clones for "+ Add line". No behavior change yet (JS still the old version until Task 4), so the page keeps working throughout.

**Files:**
- Modify: `app/opening_balances/templates/opening_balances/form.html`

**Interfaces:**
- Produces (DOM contract consumed by Task 4's JS and Task 3's e2e):
  - Each row: `<tr class="ob-line">` containing `select.ob-account[name=account_id]`, `input.ob-debit[name=debit]`, `input.ob-credit[name=credit]`, `button.ob-remove`.
  - A hidden `<template id="ob-row-template">` holding one blank `.ob-line` (present only when `editable`).
  - Each account `<select>` starts with a blank `<option value="" placeholder>` then all accounts (`disabled` on groups, `'— ' * depth` indent, `code : name`).
  - Assets loaded: `choices.min.css`, `transactions.css`, `choices.min.js`, `search-select.js`, `transaction-utils.js`, then `opening_balances.js?v=3`.

- [ ] **Step 1: Replace the whole content block of `form.html` with the macro-based version**

Replace the entire file `app/opening_balances/templates/opening_balances/form.html` with:

```jinja
{% extends "base.html" %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='choices.min.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='transactions.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='opening_balances.css') }}?v=2">
{# Save only edits drafts: a posted opening is read-only until re-opened (see save_draft guard). #}
{% set editable = can_edit and not locked and (not entry or entry.status == 'draft') %}

{# One row of the opening-balances grid — used by the entry rows, the starter row,
   and the #ob-row-template that JS clones for "+ Add line". #}
{% macro ob_row(accounts, line=None, editable=True) %}
<tr class="ob-line">
  <td>
    <select name="account_id" class="ob-account" {{ 'disabled' if not editable else '' }}>
      <option value="" placeholder>— Select account —</option>
      {% for a in accounts %}
        <option value="{{ a.id }}" {{ 'disabled' if a.is_group else '' }}
          {{ 'selected' if line and a.id == line.account_id else '' }}>
          {{ '— ' * a.depth }}{{ a.code }} : {{ a.name }}
        </option>
      {% endfor %}
    </select>
  </td>
  <td class="num"><input type="text" name="debit" class="ob-debit"
        value="{{ '%.2f'|format(line.debit_amount) if line and line.debit_amount else '' }}"
        {{ 'disabled' if not editable else '' }}></td>
  <td class="num"><input type="text" name="credit" class="ob-credit"
        value="{{ '%.2f'|format(line.credit_amount) if line and line.credit_amount else '' }}"
        {{ 'disabled' if not editable else '' }}></td>
  <td><button type="button" class="ob-remove" {{ 'disabled' if not editable else '' }}>×</button></td>
</tr>
{% endmacro %}

<div class="page-opening-balances">
  <header class="page-head">
    <h1>Opening Balances</h1>
    {% if locked %}<span class="badge badge-locked">Finalized — locked</span>{% endif %}
  </header>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}
      <div class="flash flash-{{ category }}">{{ message }}</div>
    {% endfor %}
  {% endwith %}

  <p class="help-text">
    Enter this branch's balances as of the cutover date. Retained Earnings here carries
    <strong>prior-year</strong> accumulated earnings only — enter this year's profit-to-date on the
    revenue and expense accounts, not in opening Retained Earnings, so it isn't counted twice.
  </p>

  <form method="post" action="{{ url_for('opening_balances.save_draft') }}" id="ob-form">
    {{ form.hidden_tag() }}
    <label>Cutover Date
      <input type="date" name="cutover_date"
             value="{{ entry.entry_date.strftime('%Y-%m-%d') if entry else (form.cutover_date.data.strftime('%Y-%m-%d') if form.cutover_date.data else '') }}"
             {{ 'disabled' if not editable else '' }}>
    </label>

    <table class="ob-lines" id="ob-lines">
      <thead><tr><th>Account</th><th class="num">Debit</th><th class="num">Credit</th><th></th></tr></thead>
      <tbody>
        {% if entry %}
          {% for line in entry.lines %}
            {{ ob_row(accounts, line=line, editable=editable) }}
          {% endfor %}
        {% elif editable %}
          {{ ob_row(accounts, editable=True) }}
        {% endif %}
      </tbody>
    </table>

    {% if editable %}
      {# Cloned by "+ Add line" JS. Kept out of the tbody so the on-load upgrade skips it. #}
      <template id="ob-row-template">{{ ob_row(accounts, editable=True) }}</template>
      <button type="button" id="ob-add-row">+ Add line</button>
    {% endif %}

    <div class="ob-totals">
      <span>Total Debit: <strong>₱<span id="ob-total-debit">0.00</span></strong></span>
      <span>Total Credit: <strong>₱<span id="ob-total-credit">0.00</span></strong></span>
      <span>Difference: <strong>₱<span id="ob-diff">0.00</span></strong></span>
    </div>

    {% if editable %}
      <div class="ob-actions">
        <button type="submit">{{ 'Update' if entry else 'Save' }}</button>
      </div>
    {% endif %}
  </form>

  {% if can_edit and not locked and entry and entry.status == 'draft' %}
    <form method="post" action="{{ url_for('opening_balances.post_entry') }}">
      {{ form.csrf_token }}
      <button type="submit" id="ob-post">Post</button>
    </form>
  {% endif %}

  {% if can_edit and not locked and entry and entry.status == 'posted' %}
    <form method="post" action="{{ url_for('opening_balances.reopen') }}">
      {{ form.csrf_token }}
      <button type="submit">Edit</button>
    </form>
  {% endif %}

  {% if can_finalize and not locked and entry and entry.status == 'posted' %}
    <button type="button" id="ob-finalize-open">Finalize</button>
    <div class="modal" id="ob-finalize-modal" hidden>
      <div class="modal-body">
        <p>Finalize locks the opening balances for this branch. Later corrections require an adjusting journal entry. Continue?</p>
        <form method="post" action="{{ url_for('opening_balances.finalize') }}">
          {{ form.csrf_token }}
          <button type="submit">Yes, finalize</button>
          <button type="button" id="ob-finalize-cancel">Cancel</button>
        </form>
      </div>
    </div>
  {% endif %}
</div>

<script src="{{ url_for('static', filename='choices.min.js') }}"></script>
<script src="{{ url_for('static', filename='search-select.js') }}"></script>
<script src="{{ url_for('static', filename='transaction-utils.js') }}"></script>
<script src="{{ url_for('static', filename='js/opening_balances.js') }}?v=3"></script>
{% endblock %}
```

- [ ] **Step 2: Verify the page still renders (old JS, no crash)**

Restart is NOT needed (template + static only). In the already-running server on :5050, load `http://127.0.0.1:5050/opening-balances`. Expected: page renders; view source shows `id="ob-row-template"` and the `choices.min.js` / `search-select.js` / `transaction-utils.js` script tags. The account field is still a plain `<select>` at this point (JS not yet rewritten) — that's expected.

- [ ] **Step 3: Commit**

```bash
git add app/opening_balances/templates/opening_balances/form.html
git commit -m "feat(opening-balances): row macro + Choices/transaction assets + row template"
```

---

## Task 3: e2e smoke (RED) — search-select + focus/blur + auto-clear + round-trip

Write the acceptance test first. It FAILS now (account is still a plain `<select>`; no `.choices`, no comma formatting) and passes after Task 4.

**Files:**
- Create: `tests/e2e/test_opening_balances_smoke.py`
- Modify: `pytest.ini` (register the marker)

**Interfaces:**
- Consumes: `logged_in_page`, `e2e_server` fixtures (`tests/e2e/conftest.py`); the DOM contract from Task 2. Seed COA (`seed_minimal`) includes leaf `10101 Cash on Hand`.
- Produces: the `opening_balances` marker + the e2e path referenced by Task 4's regression-map entry.

- [ ] **Step 1: Register the marker in `pytest.ini`**

In `pytest.ini`, in the `markers =` block, after the `settings:` line add:

```ini
    opening_balances: Opening Balances module e2e tests
```

- [ ] **Step 2: Write the e2e smoke**

```python
# tests/e2e/test_opening_balances_smoke.py
"""Playwright e2e smoke for the Opening Balances line item — Choices.js account
search-select + Debit/Credit focus/blur formatting and Debit-XOR-Credit auto-clear.
These are JS-only behaviours pytest's HTML-only tests can't see.

Marked `opening_balances` so `pytest -m opening_balances` runs them.
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.opening_balances]

OB = '/opening-balances'
ROW = 'tr.ob-line'


def _first_row(page):
    return page.locator(ROW).first


def _pick_account(page, row, text):
    """Open the row's Choices account picker and click the option containing `text`."""
    row.locator('.choices__inner').click()
    page.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def test_account_is_search_select(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    assert _first_row(page).locator('.choices').count() == 1


def test_debit_blurs_to_formatted_amount(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    row = _first_row(page)
    deb = row.locator('.ob-debit')
    deb.click()
    deb.fill('5000')
    row.locator('.ob-credit').click()          # blur the debit field
    assert deb.input_value() == '5,000.00'


def test_entering_debit_clears_credit(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    row = _first_row(page)
    deb = row.locator('.ob-debit')
    cred = row.locator('.ob-credit')
    cred.click(); cred.fill('200'); deb.click()      # blur credit
    assert cred.input_value() == '200.00'
    deb.fill('5000'); cred.click()                   # blur debit -> credit clears
    assert deb.input_value() == '5,000.00'
    assert cred.input_value() == ''


def test_add_and_remove_line(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    assert page.locator(ROW).count() == 1
    page.click('#ob-add-row')
    assert page.locator(ROW).count() == 2
    assert page.locator(ROW).nth(1).locator('.choices').count() == 1
    page.locator(ROW).nth(1).locator('.ob-remove').click()
    assert page.locator(ROW).count() == 1


def test_save_draft_persists_formatted_row(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + OB)
    page.wait_for_selector(ROW)
    row = _first_row(page)
    _pick_account(page, row, 'Cash on Hand')
    deb = row.locator('.ob-debit')
    deb.click(); deb.fill('5000'); row.locator('.ob-credit').click()
    page.click('#ob-form button[type="submit"]')
    page.wait_for_selector(ROW)
    assert _first_row(page).locator('.ob-debit').input_value() == '5,000.00'
```

- [ ] **Step 3: Run the e2e — expect RED**

Run: `venv/Scripts/python -m pytest tests/e2e/test_opening_balances_smoke.py -m opening_balances -p no:cacheprovider --no-cov`
Expected: FAIL — `test_account_is_search_select` finds `.choices` count `0`, and the formatting tests see `5000` not `5,000.00` (the current JS does none of this). If instead it errors on collection (marker/fixture), fix that and re-run until the failures are the behavioral ones above.

- [ ] **Step 4: Commit (RED test + marker)**

```bash
git add tests/e2e/test_opening_balances_smoke.py pytest.ini
git commit -m "test(opening-balances): e2e smoke for search-select + focus/blur (RED)"
```

---

## Task 4: Rewrite `opening_balances.js` + CSS cleanup (GREEN)

Implement the behavior so Task 3 passes.

**Files:**
- Rewrite: `app/static/js/opening_balances.js`
- Modify: `app/static/opening_balances.css`

**Interfaces:**
- Consumes: `initSearchSelect(selectEl)` (global, from `search-select.js`); `amtFmt(n)` (global, from `transaction-utils.js`); the DOM contract from Task 2.
- Produces: the runtime behavior asserted by Task 3.

- [ ] **Step 1: Replace `app/static/js/opening_balances.js` entirely**

```javascript
(function () {
  function num(v) { return parseFloat((v || '').toString().replace(/,/g, '')) || 0; }

  function recalc() {
    var d = 0, c = 0;
    document.querySelectorAll('#ob-lines .ob-line').forEach(function (row) {
      d += num(row.querySelector('.ob-debit').value);
      c += num(row.querySelector('.ob-credit').value);
    });
    var diff = d - c;
    document.getElementById('ob-total-debit').textContent = amtFmt(d);
    document.getElementById('ob-total-credit').textContent = amtFmt(c);
    document.getElementById('ob-diff').textContent = amtFmt(diff);
    var post = document.getElementById('ob-post');
    if (post) { post.disabled = Math.abs(diff) > 0.001 || d <= 0; }
  }

  // Focus: show a plain, comma-free number and select it for easy overwrite.
  function obAmtFocus(el) {
    var n = num(el.value);
    el.value = n > 0 ? String(n) : '';
    el.select();
  }

  // Format only (no side effects) — used to normalise server-rendered values on load.
  function obFormat(el) {
    var n = num(el.value);
    el.value = n > 0 ? amtFmt(n) : '';
  }

  // Blur: format this field; if it now holds an amount, clear the sibling so the row
  // is Debit XOR Credit; then recompute totals.
  function obBlur(el, siblingSel) {
    var n = num(el.value);
    el.value = n > 0 ? amtFmt(n) : '';
    if (n > 0) {
      var sib = el.closest('.ob-line').querySelector(siblingSel);
      if (sib) { sib.value = ''; }
    }
    recalc();
  }

  function wireRow(row) {
    var acct = row.querySelector('.ob-account');
    if (acct && !acct.disabled && typeof initSearchSelect === 'function'
        && !acct.closest('.choices')) {
      initSearchSelect(acct);
    }
    var deb = row.querySelector('.ob-debit');
    var cred = row.querySelector('.ob-credit');
    if (deb && !deb.disabled) {
      deb.addEventListener('focus', function () { obAmtFocus(deb); });
      deb.addEventListener('blur', function () { obBlur(deb, '.ob-credit'); });
    }
    if (cred && !cred.disabled) {
      cred.addEventListener('focus', function () { obAmtFocus(cred); });
      cred.addEventListener('blur', function () { obBlur(cred, '.ob-debit'); });
    }
    var rm = row.querySelector('.ob-remove');
    if (rm) { rm.addEventListener('click', function () { row.remove(); recalc(); }); }
  }

  var addBtn = document.getElementById('ob-add-row');
  var tpl = document.getElementById('ob-row-template');
  if (addBtn && tpl) {
    addBtn.addEventListener('click', function () {
      var body = document.querySelector('#ob-lines tbody');
      body.appendChild(tpl.content.cloneNode(true));
      var rows = body.querySelectorAll('.ob-line');
      wireRow(rows[rows.length - 1]);
      recalc();
    });
  }

  // Upgrade server-rendered rows: normalise existing amounts, init pickers, wire events.
  document.querySelectorAll('#ob-lines .ob-line').forEach(function (row) {
    var deb = row.querySelector('.ob-debit');
    var cred = row.querySelector('.ob-credit');
    if (deb) { obFormat(deb); }
    if (cred) { obFormat(cred); }
    wireRow(row);
  });
  recalc();

  var fOpen = document.getElementById('ob-finalize-open');
  var fModal = document.getElementById('ob-finalize-modal');
  var fCancel = document.getElementById('ob-finalize-cancel');
  if (fOpen && fModal) { fOpen.addEventListener('click', function () { fModal.hidden = false; }); }
  if (fCancel && fModal) { fCancel.addEventListener('click', function () { fModal.hidden = true; }); }
})();
```

- [ ] **Step 2: Clean up `app/static/opening_balances.css`**

The account cell now hosts a Choices widget (styled by `transactions.css`), so the native-`<select>` styling in the shared input rule is dead. In `app/static/opening_balances.css`, edit the combined input rule that currently starts:

```css
.page-opening-balances .ob-account,
.page-opening-balances .ob-debit,
.page-opening-balances .ob-credit {
```

Remove the `.page-opening-balances .ob-account,` line from that selector (leave `.ob-debit` + `.ob-credit`). Then delete the two now-orphaned `.ob-account`-only rules (`:focus` and `:disabled` include `.ob-account` — drop the `.ob-account` line from each of those grouped selectors too). Keep everything else (table-layout:fixed, column widths, number-input styling, remove-button, totals). The account column width (`td:nth-child(1) { width: 56% }`) stays and now sizes the Choices widget.

- [ ] **Step 3: Run the e2e — expect GREEN**

Run: `venv/Scripts/python -m pytest tests/e2e/test_opening_balances_smoke.py -m opening_balances -p no:cacheprovider --no-cov`
Expected: 5 passed. If `test_save_draft_persists_formatted_row` fails because the selected account didn't post, confirm `seed_minimal` renders `10101 Cash on Hand` as a leaf (it does) and that `_pick_account` clicked a `.choices__item` (not the disabled group header).

- [ ] **Step 4: Browser sanity check**

Reload `http://127.0.0.1:5050/opening-balances`: the Account field is a typeahead; typing filters; the full title shows; enter a Debit → it formats to `1,234.56` on blur and the Credit on that row clears; "+ Add line" adds a working search-select row; totals update.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/opening_balances.js app/static/opening_balances.css
git commit -m "feat(opening-balances): search-select account + Debit/Credit focus-blur format + auto-clear"
```

---

## Task 5: Guard the new surface — regression-map + INDEX

Wire `opening_balances` into the regression guard so its own JS and the shared files it now depends on trigger the e2e, and index the plan.

**Files:**
- Modify: `.claude/regression-map.json`
- Modify/Create: `docs/superpowers/plans/INDEX.md`

**Interfaces:**
- Consumes: the marker + e2e path from Task 3.

- [ ] **Step 1: Add the module entry**

In `.claude/regression-map.json`, in `"modules"`, add after the `sales_orders` line:

```json
    "opening_balances": { "marker": "opening_balances", "e2e": "tests/e2e/test_opening_balances_smoke.py" },
```

- [ ] **Step 2: Map the files that now affect Opening Balances**

In `"blast_radius"`, add these keys (own files) near the other `app/static/*` entries:

```json
    "app/static/js/opening_balances.js":     ["opening_balances"],
    "app/opening_balances/views.py":      ["opening_balances"],
```

And append `"opening_balances"` to the dependent arrays of the shared files OB now loads: `app/static/transaction-utils.js`, `app/static/search-select.js`, `app/static/transactions.css`, `app/static/choices.min.js`, `app/static/choices.min.css`. Example for the first:

```json
    "app/static/transaction-utils.js":     ["accounts_payable", "cash_disbursements", "sales_invoices", "cash_receipts", "opening_balances"],
```

> **Load caveat (see memory `project-regression-guard` item on the combined e2e gate):** the per-push e2e gate runs every affected module's smoke against ONE shared dev server, which can flake the last module under cumulative load. If wiring OB onto the big shared-file lists makes the gate flaky, drop OB from those shared-file arrays (keep the `opening_balances.js`/`views.py` keys + the module entry) or set the module's `"e2e"` to `null` and run `pytest -m opening_balances` manually — mirroring the `cash_disbursements` precedent.

- [ ] **Step 3: Validate the JSON**

Run: `venv/Scripts/python -c "import json; json.load(open('.claude/regression-map.json')); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Index the plan**

Create `docs/superpowers/plans/INDEX.md` if it does not exist, else append a row. Content (create case):

```markdown
# CAS Implementation Plans — Index

| Date | Plan | Status |
|---|---|---|
| 2026-07-03 | [Opening Balances — SI line-item parity](2026-07-03-opening-balances-si-parity.md) | Ready to implement |
```

- [ ] **Step 5: Commit**

```bash
git add .claude/regression-map.json docs/superpowers/plans/INDEX.md
git commit -m "chore(opening-balances): guard the module + index the plan"
```

---

## Self-Review

**1. Spec coverage**
- Account search-select → Task 2 (assets + macro) + Task 4 (`initSearchSelect` per row). ✓
- Number focus/blur + `1,234.56` format → Task 4 (`obAmtFocus`/`obBlur`/`obFormat`, `amtFmt`). ✓
- Auto-clear sibling (Debit XOR Credit) → Task 4 (`obBlur` sibling clear) + Task 3 test. ✓
- Blank-on-zero display → Task 4 (`obFormat`/`obBlur` `n > 0 ? … : ''`). ✓
- Groups shown disabled → Task 2 macro (`disabled if a.is_group`, `'— ' * depth`). ✓
- No server change → Task 1 characterization test proves comma tolerance; no view/model/migration edits anywhere. ✓
- Programmatic new rows (Choices can't be cloned live) → Task 2 `<template>` + Task 4 `tpl.content.cloneNode`. ✓ (Refinement vs spec: `<template>` clone instead of a JSON blob — same intent, reuses Jinja option rendering, avoids `Decimal` serialization.)
- Read-only states → Task 2 (`disabled` attrs) + Task 4 (`!disabled` guards skip Choices/handlers). ✓
- Testing: e2e smoke (Task 3) + comma-parse unit test (Task 1) + regression-map (Task 5). ✓

**2. Placeholder scan** — no TBD/TODO; every code step shows full content. The only conditional instruction (CSS line removal, Task 4 Step 2) names the exact selector lines to change. ✓

**3. Type/name consistency** — `initSearchSelect(selectEl)`, `amtFmt(n)` used exactly as defined in the shared files; DOM classes (`ob-account`/`ob-debit`/`ob-credit`/`ob-remove`), ids (`ob-lines`/`ob-add-row`/`ob-row-template`/`ob-total-debit`/`ob-total-credit`/`ob-diff`/`ob-post`/`ob-form`), and the `opening_balances` marker/module name match across Tasks 2–5. ✓
