# Sales Invoice Pre-printed Layout Designer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin drag-and-drop the fields of the Sales Invoice **pre-printed** print page into position, reorder/hide the line-item columns, set per-element font size + bold and a page-wide font family, and save a layout that persists company-wide and drives the actual print.

**Architecture:** All *logic* lives server-side where pytest can test it — a layout model (defaults + sanitize/merge) persisted as one JSON string in an `app_settings` row (`sv_preprinted_layout`), an admin-only save route, and a template that renders every element absolutely positioned per the saved layout. The browser layer is a **thin** editor (`sv_preprinted_designer.js`): it toggles edit mode, drags elements (writing `style.left/top`), reorders/hides columns, applies font controls, then serializes the DOM to the same JSON and POSTs it. Positioning is **drag-only** — no coordinate inputs anywhere. Client behavior is verified by Playwright e2e (the JS layer pytest-HTML tests can't see).

**Tech Stack:** Flask + SQLAlchemy (AppSettings key/value), Jinja2, vanilla JS (no new deps), Playwright for e2e.

## Global Constraints

- **Drag-and-drop only for positioning** — never render an x/y (or width) number input. The *only* control inputs are: font-family (page), font-size + bold (per selected element), and per-column show/hide toggles + drag-to-reorder.
- **Admin-only edit.** The "Edit Layout" button, the editor, and the save route are gated to `current_user.role == 'admin'` (use the existing `admin_only`/`admin_required` decorator). Everyone else prints read-only.
- **Persistence = one `app_settings` row** keyed `sv_preprinted_layout`, value = JSON. No new table, no migration. (The dormant `print_layouts` table stays dormant.)
- **Coordinates are pixels on a fixed A4 canvas** 794×1123 (A4 @96dpi). Screen == print.
- **Sanitize on both read and write.** Never trust stored or POSTed JSON: whitelist field keys and column keys, clamp numerics to ranges, coerce bools, drop unknowns, and guarantee every known field/column is present (so a layout saved before a new field existed still renders it at its default).
- **Audit every save** via `log_audit(module='sales_invoices', action='update', record_identifier='sv_preprinted_layout', ...)` (project rule: writes are audited).
- **Peso sign** uses the literal `₱` (U+20B1), never `&#8369;`.
- **Static assets** carry a manual `?v=N`; bump every `<link>`/`<script>` that loads a changed asset in the same commit.
- **TDD.** Server logic (Tasks 1–3) is red-green pytest. Client tasks (4–6) are red-green Playwright e2e (`pytest -m e2e`). No production code without a failing test first.

---

## File Structure

- **Create `app/sales_invoices/preprinted_layout.py`** — the layout model: `DEFAULT_SV_PREPRINTED_LAYOUT`, field/column/font whitelists, `sanitize_layout()`, `get_layout()`, `save_layout()`. Single source of truth for shape + defaults.
- **Modify `app/sales_invoices/views.py`** — `print_invoice` passes `layout` + `can_edit_layout`; new `save_print_layout` POST route (admin-only).
- **Rewrite `app/sales_invoices/templates/sales_invoices/print_preprinted.html`** — an absolutely-positioned A4 canvas driven entirely by `layout`; includes the editor assets + Edit button (admin only).
- **Create `app/static/js/sv_preprinted_designer.js`** — the thin editor (drag, columns, fonts, serialize+POST).
- **Create `app/static/css/sv_preprinted_designer.css`** — edit-mode chrome (handles, selection outline, toolbar).
- **Create `tests/unit/test_preprinted_layout.py`** — model tests.
- **Create `tests/integration/test_sv_print_layout_route.py`** — save-route tests.
- **Extend `tests/integration/test_sv_print_form.py`** — rendering-from-layout tests.
- **Create `tests/e2e/test_sv_preprinted_designer.py`** — Playwright editor tests.

**Layout JSON shape (the contract every task shares):**
```json
{
  "page": { "fontFamily": "Arial, sans-serif" },
  "fields": {
    "invoice_no":        {"x":520,"y":50,"fontSize":12,"bold":true},
    "invoice_date":      {"x":520,"y":74,"fontSize":11,"bold":false},
    "due_date":          {"x":520,"y":98,"fontSize":11,"bold":false},
    "terms":             {"x":520,"y":122,"fontSize":11,"bold":false},
    "customer_name":     {"x":40,"y":50,"fontSize":12,"bold":true},
    "customer_tin":      {"x":40,"y":74,"fontSize":11,"bold":false},
    "customer_address":  {"x":40,"y":98,"fontSize":11,"bold":false},
    "customer_po":       {"x":40,"y":122,"fontSize":11,"bold":false},
    "amount_collectible":{"x":520,"y":560,"fontSize":13,"bold":true},
    "notes":             {"x":40,"y":600,"fontSize":10,"bold":false}
  },
  "lineItems": {
    "x":40,"y":190,"width":714,"fontSize":10,"bold":false,
    "columns":[
      {"key":"line_number","visible":true,"width":30},
      {"key":"description","visible":true,"width":300},
      {"key":"product","visible":false,"width":120},
      {"key":"quantity","visible":true,"width":70},
      {"key":"uom","visible":true,"width":60},
      {"key":"unit_price","visible":true,"width":90},
      {"key":"amount","visible":true,"width":100}
    ]
  }
}
```

---

### Task 1: Layout model — defaults, sanitize, get, save

**Files:**
- Create: `app/sales_invoices/preprinted_layout.py`
- Test: `tests/unit/test_preprinted_layout.py`

**Interfaces:**
- Produces: `DEFAULT_SV_PREPRINTED_LAYOUT` (dict), `FIELD_KEYS` (list[str]), `COLUMN_KEYS` (list[str]), `ALLOWED_FONTS` (list[str]), `LAYOUT_SETTING_KEY = 'sv_preprinted_layout'`, `sanitize_layout(raw: dict) -> dict`, `get_layout() -> dict`, `save_layout(raw: dict, username: str) -> dict`.
- Consumes: `app.settings.AppSettings.get_setting/set_setting`, `app.audit.utils.log_audit`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_preprinted_layout.py
import json
import pytest
from app.settings import AppSettings
from app.sales_invoices.preprinted_layout import (
    DEFAULT_SV_PREPRINTED_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, COLUMN_KEYS,
    sanitize_layout, get_layout, save_layout,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.unit, pytest.mark.sales_invoices]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert [c['key'] for c in out['lineItems']['columns']] == COLUMN_KEYS
        assert out['page']['fontFamily'] == DEFAULT_SV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_unknown_field_dropped_known_field_kept(self):
        out = sanitize_layout({'fields': {'invoice_no': {'x': 111, 'y': 222},
                                          'evil_key': {'x': 5, 'y': 5}}})
        assert 'evil_key' not in out['fields']
        assert out['fields']['invoice_no']['x'] == 111
        assert out['fields']['invoice_no']['y'] == 222
        # missing field still present at its default
        assert out['fields']['terms'] == DEFAULT_SV_PREPRINTED_LAYOUT['fields']['terms']

    def test_coords_and_sizes_clamped_and_coerced(self):
        out = sanitize_layout({'fields': {'invoice_no': {'x': -50, 'y': 99999,
                                                         'fontSize': 999, 'bold': 'yes'}}})
        f = out['fields']['invoice_no']
        assert f['x'] == 0            # clamped to >= 0
        assert f['y'] == 1123         # clamped to canvas height
        assert f['fontSize'] == 72    # clamped to <= 72
        assert f['bold'] is True      # truthy coerced to bool

    def test_disallowed_font_falls_back_to_default(self):
        out = sanitize_layout({'page': {'fontFamily': 'Comic Sans MS'}})
        assert out['page']['fontFamily'] == DEFAULT_SV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_columns_reorder_and_hide_preserved_unknown_dropped(self):
        out = sanitize_layout({'lineItems': {'columns': [
            {'key': 'amount', 'visible': True, 'width': 100},
            {'key': 'description', 'visible': False, 'width': 300},
            {'key': 'bogus', 'visible': True, 'width': 50},
        ]}})
        keys = [c['key'] for c in out['lineItems']['columns']]
        assert keys[0] == 'amount' and keys[1] == 'description'   # order preserved
        assert 'bogus' not in keys                                # unknown dropped
        assert set(keys) == set(COLUMN_KEYS)                      # missing ones appended
        assert out['lineItems']['columns'][1]['visible'] is False


class TestGetSave:
    def test_get_returns_default_when_unset(self, db_session):
        assert get_layout()['fields']['invoice_no'] == \
            DEFAULT_SV_PREPRINTED_LAYOUT['fields']['invoice_no']

    def test_get_returns_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)

    def test_save_persists_sanitized_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'invoice_no': {'x': 300, 'y': 90}}},
                             admin_user.username)
        assert result['fields']['invoice_no']['x'] == 300
        stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
        assert stored['fields']['invoice_no']['x'] == 300
        entry = AuditLog.query.filter_by(
            module='sales_invoices', record_identifier='sv_preprinted_layout'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/test_preprinted_layout.py -q`
Expected: FAIL/ERROR — `ModuleNotFoundError: app.sales_invoices.preprinted_layout`.

- [ ] **Step 3: Implement the model**

```python
# app/sales_invoices/preprinted_layout.py
"""Layout model for the Sales Invoice pre-printed print designer (SI-P-71).

The whole layout is one JSON value in an app_settings row. Everything is sanitized
on read AND write against these defaults, so stored or POSTed JSON can never inject
unknown keys, out-of-range numbers, or an unlisted font, and a layout saved before a
new field/column existed still renders that field/column at its default.
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit

LAYOUT_SETTING_KEY = 'sv_preprinted_layout'

CANVAS_W = 794      # A4 @96dpi
CANVAS_H = 1123
FONT_MIN, FONT_MAX = 6, 72
WIDTH_MIN, WIDTH_MAX = 10, 794

ALLOWED_FONTS = [
    'Arial, sans-serif',
    'Helvetica, Arial, sans-serif',
    '"Times New Roman", Times, serif',
    'Georgia, serif',
    '"Courier New", Courier, monospace',
    'Verdana, Geneva, sans-serif',
]

FIELD_KEYS = [
    'invoice_no', 'invoice_date', 'due_date', 'terms',
    'customer_name', 'customer_tin', 'customer_address', 'customer_po',
    'amount_collectible', 'notes',
]

COLUMN_KEYS = [
    'line_number', 'description', 'product', 'quantity',
    'uom', 'unit_price', 'amount',
]

DEFAULT_SV_PREPRINTED_LAYOUT = {
    'page': {'fontFamily': 'Arial, sans-serif'},
    'fields': {
        'invoice_no':         {'x': 520, 'y': 50,  'fontSize': 12, 'bold': True},
        'invoice_date':       {'x': 520, 'y': 74,  'fontSize': 11, 'bold': False},
        'due_date':           {'x': 520, 'y': 98,  'fontSize': 11, 'bold': False},
        'terms':              {'x': 520, 'y': 122, 'fontSize': 11, 'bold': False},
        'customer_name':      {'x': 40,  'y': 50,  'fontSize': 12, 'bold': True},
        'customer_tin':       {'x': 40,  'y': 74,  'fontSize': 11, 'bold': False},
        'customer_address':   {'x': 40,  'y': 98,  'fontSize': 11, 'bold': False},
        'customer_po':        {'x': 40,  'y': 122, 'fontSize': 11, 'bold': False},
        'amount_collectible': {'x': 520, 'y': 560, 'fontSize': 13, 'bold': True},
        'notes':              {'x': 40,  'y': 600, 'fontSize': 10, 'bold': False},
    },
    'lineItems': {
        'x': 40, 'y': 190, 'width': 714, 'fontSize': 10, 'bold': False,
        'columns': [
            {'key': 'line_number', 'visible': True,  'width': 30},
            {'key': 'description', 'visible': True,  'width': 300},
            {'key': 'product',     'visible': False, 'width': 120},
            {'key': 'quantity',    'visible': True,  'width': 70},
            {'key': 'uom',         'visible': True,  'width': 60},
            {'key': 'unit_price',  'visible': True,  'width': 90},
            {'key': 'amount',      'visible': True,  'width': 100},
        ],
    },
}


def _clamp(value, lo, hi, fallback):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(hi, n))


def _clean_box(raw, default):
    raw = raw if isinstance(raw, dict) else {}
    return {
        'x': _clamp(raw.get('x'), 0, CANVAS_W, default['x']),
        'y': _clamp(raw.get('y'), 0, CANVAS_H, default['y']),
        'fontSize': _clamp(raw.get('fontSize'), FONT_MIN, FONT_MAX, default['fontSize']),
        'bold': bool(raw.get('bold', default['bold'])),
    }


def _clean_columns(raw):
    raw = raw if isinstance(raw, list) else []
    by_key = {c.get('key'): c for c in raw if isinstance(c, dict) and c.get('key') in COLUMN_KEYS}
    defaults = {c['key']: c for c in DEFAULT_SV_PREPRINTED_LAYOUT['lineItems']['columns']}
    ordered_keys = [c['key'] for c in raw
                    if isinstance(c, dict) and c.get('key') in COLUMN_KEYS]
    # keep first-seen order, then append any known column the input omitted
    seen, order = set(), []
    for k in ordered_keys + COLUMN_KEYS:
        if k not in seen:
            seen.add(k); order.append(k)
    out = []
    for k in order:
        src = by_key.get(k, {})
        d = defaults[k]
        out.append({
            'key': k,
            'visible': bool(src.get('visible', d['visible'])),
            'width': _clamp(src.get('width'), WIDTH_MIN, WIDTH_MAX, d['width']),
        })
    return out


def sanitize_layout(raw):
    """Return a fully-populated, validated layout built from `raw` over the defaults."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_SV_PREPRINTED_LAYOUT
    font = (raw.get('page') or {}).get('fontFamily')
    page = {'fontFamily': font if font in ALLOWED_FONTS else d['page']['fontFamily']}
    raw_fields = raw.get('fields') if isinstance(raw.get('fields'), dict) else {}
    fields = {k: _clean_box(raw_fields.get(k), d['fields'][k]) for k in FIELD_KEYS}
    raw_li = raw.get('lineItems') if isinstance(raw.get('lineItems'), dict) else {}
    dli = d['lineItems']
    line_items = {
        'x': _clamp(raw_li.get('x'), 0, CANVAS_W, dli['x']),
        'y': _clamp(raw_li.get('y'), 0, CANVAS_H, dli['y']),
        'width': _clamp(raw_li.get('width'), WIDTH_MIN, WIDTH_MAX, dli['width']),
        'fontSize': _clamp(raw_li.get('fontSize'), FONT_MIN, FONT_MAX, dli['fontSize']),
        'bold': bool(raw_li.get('bold', dli['bold'])),
        'columns': _clean_columns(raw_li.get('columns')),
    }
    return {'page': page, 'fields': fields, 'lineItems': line_items}


def get_layout():
    """Current sanitized layout (defaults if unset or corrupt)."""
    stored = AppSettings.get_setting(LAYOUT_SETTING_KEY)
    if not stored:
        return copy.deepcopy(DEFAULT_SV_PREPRINTED_LAYOUT)
    try:
        return sanitize_layout(json.loads(stored))
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_SV_PREPRINTED_LAYOUT)


def save_layout(raw, username):
    """Sanitize, persist, audit, and return the clean layout."""
    clean = sanitize_layout(raw)
    old = AppSettings.get_setting(LAYOUT_SETTING_KEY)
    AppSettings.set_setting(LAYOUT_SETTING_KEY, json.dumps(clean), updated_by=username)
    log_audit(module='sales_invoices', action='update', record_id=None,
              record_identifier='sv_preprinted_layout',
              old_values={'layout': old}, new_values={'layout': json.dumps(clean)},
              notes='Pre-printed layout updated')
    return clean
```

- [ ] **Step 4: Run to verify green**

Run: `pytest tests/unit/test_preprinted_layout.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add app/sales_invoices/preprinted_layout.py tests/unit/test_preprinted_layout.py
git commit -m "feat(si-preprinted): layout model — defaults, sanitize, get/save (SI-P-71 Task 1)"
```

---

### Task 2: Admin-only save route

**Files:**
- Modify: `app/sales_invoices/views.py`
- Test: `tests/integration/test_sv_print_layout_route.py`

**Interfaces:**
- Consumes: `preprinted_layout.save_layout`, the existing `admin_required` decorator in `app/users/views.py` (import it the same way other SI admin actions do; if SI has no admin decorator in use, gate inline with `if current_user.role != 'admin': abort(403)`).
- Produces: `POST /sales-invoices/print-layout` returning `{"ok": true}` (200) or `{"ok": false, "error": ...}` (400); endpoint name `sales_invoices.save_print_layout`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_sv_print_layout_route.py
import json
import pytest
from app.settings import AppSettings
from app.sales_invoices.preprinted_layout import LAYOUT_SETTING_KEY

pytestmark = [pytest.mark.integration, pytest.mark.sales_invoices]

URL = '/sales-invoices/print-layout'


def login(client, u='admin', p='admin123'):
    client.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


def test_admin_saves_layout(client, db_session, admin_user, main_branch):
    login(client)
    payload = {'fields': {'invoice_no': {'x': 333, 'y': 44}}}
    resp = client.post(URL, json=payload)
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
    assert stored['fields']['invoice_no']['x'] == 333


def test_non_admin_forbidden(client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    resp = client.post(URL, json={'fields': {}})
    assert resp.status_code in (302, 403)               # gated
    assert AppSettings.get_setting(LAYOUT_SETTING_KEY) is None   # nothing written


def test_anonymous_redirected(client, db_session):
    resp = client.post(URL, json={'fields': {}})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_garbage_body_still_stores_sanitized_default(client, db_session, admin_user, main_branch):
    login(client)
    resp = client.post(URL, json={'fields': {'evil': {'x': 1}}, 'lineItems': 'not-a-dict'})
    assert resp.status_code == 200
    stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
    assert 'evil' not in stored['fields']
    assert isinstance(stored['lineItems']['columns'], list)
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/integration/test_sv_print_layout_route.py -q`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Implement the route** (add near `print_invoice` in `app/sales_invoices/views.py`; import `save_layout` at top: `from app.sales_invoices.preprinted_layout import get_layout, save_layout`)

```python
@sales_invoices_bp.route('/sales-invoices/print-layout', methods=['POST'])
@login_required
def save_print_layout():
    if current_user.role != 'admin':
        abort(403)
    data = request.get_json(silent=True) or {}
    clean = save_layout(data, current_user.username)
    return jsonify(ok=True, layout=clean)
```

Ensure `abort`, `jsonify`, `request`, `current_user` are imported (most already are; add what's missing).

- [ ] **Step 4: Run to verify green**

Run: `pytest tests/integration/test_sv_print_layout_route.py -q`
Expected: PASS. (Testing config disables CSRF, so the JSON POST needs no token here.)

- [ ] **Step 5: Commit**

```bash
git add app/sales_invoices/views.py tests/integration/test_sv_print_layout_route.py
git commit -m "feat(si-preprinted): admin-only save-layout route (SI-P-71 Task 2)"
```

---

### Task 3: Render the pre-printed page from the layout

**Files:**
- Modify: `app/sales_invoices/views.py` (`print_invoice`)
- Rewrite: `app/sales_invoices/templates/sales_invoices/print_preprinted.html`
- Test: extend `tests/integration/test_sv_print_form.py`

**Interfaces:**
- `print_invoice` passes `layout=get_layout()` and `can_edit_layout=(current_user.role == 'admin')` to `print_preprinted.html` (in addition to the existing `invoice`, `company`, `je_entries`, `printed_at`).

- [ ] **Step 1: Write the failing tests** (append a class to `tests/integration/test_sv_print_form.py`)

```python
class TestPreprintedLayoutRender:
    def _prep(self, client):
        from app.settings import AppSettings
        AppSettings.set_setting('sv_print_form', 'preprinted', 'system')
        login(client)

    def test_field_positioned_from_layout(self, client, db_session, admin_user,
                                          main_branch, _customer, _invoice):
        import json
        from app.settings import AppSettings
        from app.sales_invoices.preprinted_layout import get_layout
        layout = get_layout()
        layout['fields']['invoice_no']['x'] = 654
        AppSettings.set_setting('sv_preprinted_layout', json.dumps(layout), 'system')
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        # the invoice-no element carries its saved left position
        assert 'data-el="invoice_no"' in html
        assert 'left:654px' in html or 'left: 654px' in html

    def test_hidden_column_absent_visible_present(self, client, db_session, admin_user,
                                                  main_branch, _customer, _invoice):
        import json
        from app.settings import AppSettings
        from app.sales_invoices.preprinted_layout import get_layout
        layout = get_layout()
        for c in layout['lineItems']['columns']:
            if c['key'] == 'uom':
                c['visible'] = False
        AppSettings.set_setting('sv_preprinted_layout', json.dumps(layout), 'system')
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert 'data-col="amount"' in html      # a visible column renders
        assert 'data-col="uom"' not in html      # a hidden column does not

    def test_edit_button_admin_only(self, client, db_session, admin_user, accountant_user,
                                    main_branch, _customer, _invoice):
        self._prep(client)                       # logged in as admin
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert 'id="editLayoutBtn"' in html
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/integration/test_sv_print_form.py::TestPreprintedLayoutRender -q`
Expected: FAIL — markers absent (old template).

- [ ] **Step 3a: Update `print_invoice`** to pass the layout:

```python
    # inside print_invoice, replace the preprinted render path
    from app.sales_invoices.preprinted_layout import get_layout
    template = 'sales_invoices/print.html'
    extra = {}
    if sv_print_form == 'preprinted':
        template = 'sales_invoices/print_preprinted.html'
        extra = {'layout': get_layout(),
                 'can_edit_layout': current_user.role == 'admin'}
    return render_template(template, invoice=invoice, je_entries=je_entries,
                           company=company, printed_at=ph_now(), **extra)
```

- [ ] **Step 3b: Rewrite `print_preprinted.html`** as an absolutely-positioned canvas. Every field is a `<div class="pp-el" data-el="KEY" style="left:{{x}}px;top:{{y}}px;font-size:{{fs}}px;font-weight:...">`. The line-items block is `<div class="pp-el pp-lineitems" data-el="lineItems" ...>` containing a table whose columns iterate `layout.lineItems.columns` filtered to `visible`, each `<th|td data-col="KEY">`. Use a Jinja macro `field(key, value)` to DRY the field wrapper. Include the editor assets + Edit button gated by `can_edit_layout`. Full template:

```jinja
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="csrf-token" content="{{ csrf_token() }}">
<title>Sales Invoice {{ invoice.invoice_number }} — Pre-printed</title>
<link rel="stylesheet" href="{{ url_for('static', filename='css/sv_preprinted_designer.css') }}?v=1">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: {{ layout.page.fontFamily }}; color:#111; background:#eee; }
  .pp-canvas { position: relative; width: 794px; height: 1123px; margin: 16px auto;
               background:#fff; }
  .pp-el { position: absolute; white-space: nowrap; }
  .pp-lineitems table { border-collapse: collapse; }
  .pp-lineitems th, .pp-lineitems td { padding: 3px 6px; text-align: left;
               border-bottom: 1px solid #ddd; }
  .pp-lineitems th { border-bottom: 1px solid #999; font-weight: 700; }
  .pp-amount { text-align: right; font-family: monospace; }
  .pp-toolbar { max-width: 794px; margin: 12px auto 0; display: flex; gap: 8px; }
  .btn { padding: 8px 16px; border:none; border-radius:4px; font-size:13px; cursor:pointer; }
  .btn-print { background:#1565c0; color:#fff; }
  .btn-close { background:#666; color:#fff; }
  .btn-edit  { background:#2e7d32; color:#fff; }
  @media print {
    body { background:#fff; }
    .screen-only { display:none !important; }
    .pp-canvas { margin:0; }
    @page { size: A4 portrait; margin: 0; }
  }
</style>
</head>
<body data-can-edit="{{ 'true' if can_edit_layout else 'false' }}">

{% macro field(key, value, bold_default=false) %}
  {% set f = layout.fields[key] %}
  <div class="pp-el" data-el="{{ key }}"
       style="left:{{ f.x }}px;top:{{ f.y }}px;font-size:{{ f.fontSize }}px;font-weight:{{ 'bold' if f.bold else 'normal' }};">{{ value }}</div>
{% endmacro %}

<div class="pp-toolbar screen-only">
  <button class="btn btn-print" onclick="window.print()">Print</button>
  <button type="button" class="btn btn-close" onclick="window.close()">Close</button>
  {% if can_edit_layout %}
  <button type="button" id="editLayoutBtn" class="btn btn-edit">Edit Layout</button>
  {% endif %}
</div>

<div class="pp-canvas" id="ppCanvas">
  {{ field('invoice_no', 'Invoice No.: ' ~ invoice.invoice_number) }}
  {{ field('invoice_date', 'Date: ' ~ invoice.invoice_date.strftime('%d %B %Y')) }}
  {{ field('due_date', 'Due: ' ~ (invoice.due_date.strftime('%d %B %Y') if invoice.due_date else '—')) }}
  {{ field('terms', 'Terms: ' ~ (invoice.payment_terms or '—')) }}
  {{ field('customer_name', invoice.customer_name) }}
  {{ field('customer_tin', 'TIN: ' ~ (invoice.customer_tin or '—')) }}
  {{ field('customer_address', invoice.customer_address or '') }}
  {{ field('customer_po', 'PO: ' ~ (invoice.customer_po_number or '—')) }}
  {{ field('amount_collectible', '₱ ' ~ '{:,.2f}'.format(invoice.total_amount)) }}
  {{ field('notes', invoice.notes or '') }}

  {% set li = layout.lineItems %}
  <div class="pp-el pp-lineitems" data-el="lineItems"
       style="left:{{ li.x }}px;top:{{ li.y }}px;width:{{ li.width }}px;font-size:{{ li.fontSize }}px;font-weight:{{ 'bold' if li.bold else 'normal' }};">
    <table style="width:{{ li.width }}px;">
      <thead><tr>
        {% for col in li.columns if col.visible %}
        <th data-col="{{ col.key }}" style="width:{{ col.width }}px;">{{ COL_LABELS[col.key] }}</th>
        {% endfor %}
      </tr></thead>
      <tbody>
        {% for item in invoice.line_items %}
        <tr>
          {% for col in li.columns if col.visible %}
          <td data-col="{{ col.key }}" class="{{ 'pp-amount' if col.key in ('amount','unit_price','quantity') else '' }}">{{ CELL(item, col.key) }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

{% if can_edit_layout %}
<script src="{{ url_for('static', filename='js/sv_preprinted_designer.js') }}?v=1"></script>
{% endif %}
</body>
</html>
```

Provide the label/cell mapping to the template context (cleanest: compute in the view and pass as `COL_LABELS` dict + render cells with a small Jinja `{% set %}` map instead of a `CELL()` callable — a callable can't be passed cleanly, so render cell values inline). Replace the `{{ CELL(item, col.key) }}` with an inline `{% if col.key == 'description' %}{{ item.description or '—' }}{% elif col.key == 'quantity' %}...{% endif %}` chain covering all seven column keys, and pass `COL_LABELS` (a dict of key→header text) from the view. Keep the peso literal `₱`.

- [ ] **Step 4: Run to verify green**

Run: `pytest tests/integration/test_sv_print_form.py -q`
Expected: PASS (new class + existing sv_print_form tests still green — the `sv-preprinted` marker test may need updating: the rewritten template no longer contains `sv-preprinted`; update that assertion to the new marker `pp-canvas`, and keep `sv-header` absent).

- [ ] **Step 5: Commit**

```bash
git add app/sales_invoices/views.py app/sales_invoices/templates/sales_invoices/print_preprinted.html tests/integration/test_sv_print_form.py
git commit -m "feat(si-preprinted): render pre-printed page from saved layout (SI-P-71 Task 3)"
```

---

### Task 4: Editor — Edit Mode toggle + drag free elements + save

**Files:**
- Create: `app/static/js/sv_preprinted_designer.js`
- Create: `app/static/css/sv_preprinted_designer.css`
- Test: `tests/e2e/test_sv_preprinted_designer.py`

**Interfaces:** the JS reads `#ppCanvas`, toggles edit mode on `#editLayoutBtn`, drags any `.pp-el` (pointer events, writing `style.left/top`), and on "Save Layout" serializes every `.pp-el`'s position/font + the columns into the layout JSON and POSTs to `/sales-invoices/print-layout` with header `X-CSRFToken` from the `<meta name="csrf-token">`.

- [ ] **Step 1: Write the failing e2e test**

```python
# tests/e2e/test_sv_preprinted_designer.py
"""Playwright e2e for the SI pre-printed layout designer (the drag layer)."""
import json
import pytest
from app.settings import AppSettings

pytestmark = [pytest.mark.e2e, pytest.mark.sales_invoices]


def _seed_preprinted(app):
    with app.app_context():
        AppSettings.set_setting('sv_print_form', 'preprinted', 'system')


def test_drag_persists_after_save_and_reload(logged_in_page, e2e_server, app, si_invoice_id):
    _seed_preprinted(app)
    page = logged_in_page
    page.goto(f'{e2e_server}/sales-invoices/{si_invoice_id}/print')
    page.click('#editLayoutBtn')                         # enter edit mode
    el = page.locator('[data-el="invoice_no"]')
    box = el.bounding_box()
    page.mouse.move(box['x'] + 10, box['y'] + 8)
    page.mouse.down()
    page.mouse.move(box['x'] + 120, box['y'] + 60, steps=8)
    page.mouse.up()
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag')           # JS sets this on 200
    page.reload()
    left = page.locator('[data-el="invoice_no"]').evaluate("e => parseInt(e.style.left)")
    assert left > box['x']                               # moved right, persisted
```

Add an `si_invoice_id` fixture to `tests/e2e/conftest.py` if absent (create a posted invoice, return its id) — mirror how `test_si_smoke.py` obtains an invoice.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/e2e/test_sv_preprinted_designer.py -q`
Expected: FAIL — `#editLayoutBtn` toggles nothing / `#saveLayoutBtn` absent (no JS yet).

- [ ] **Step 3: Implement the editor JS + CSS**

```javascript
// app/static/js/sv_preprinted_designer.js
(function () {
  const canvas = document.getElementById('ppCanvas');
  const editBtn = document.getElementById('editLayoutBtn');
  if (!canvas || !editBtn) return;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  let editing = false;

  // --- Save button injected next to Edit ---
  const saveBtn = document.createElement('button');
  saveBtn.id = 'saveLayoutBtn'; saveBtn.type = 'button';
  saveBtn.className = 'btn btn-edit'; saveBtn.textContent = 'Save Layout';
  saveBtn.style.display = 'none';
  editBtn.after(saveBtn);

  editBtn.addEventListener('click', () => {
    editing = !editing;
    canvas.classList.toggle('pp-editing', editing);
    saveBtn.style.display = editing ? '' : 'none';
    editBtn.textContent = editing ? 'Exit Edit' : 'Edit Layout';
  });

  // --- Drag any .pp-el while editing ---
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => {
    if (!editing) return;
    const el = e.target.closest('.pp-el');
    if (!el) return;
    const r = el.getBoundingClientRect(); const c = canvas.getBoundingClientRect();
    drag = { el, dx: e.clientX - r.left, dy: e.clientY - r.top, c };
    el.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    let x = e.clientX - drag.c.left - drag.dx;
    let y = e.clientY - drag.c.top - drag.dy;
    x = Math.max(0, Math.min(canvas.clientWidth, Math.round(x)));
    y = Math.max(0, Math.min(canvas.clientHeight, Math.round(y)));
    drag.el.style.left = x + 'px';
    drag.el.style.top = y + 'px';
  });
  canvas.addEventListener('pointerup', () => { drag = null; });

  // --- Serialize DOM -> layout JSON ---
  function collect() {
    const fields = {};
    canvas.querySelectorAll('.pp-el:not(.pp-lineitems)').forEach((el) => {
      const cs = getComputedStyle(el);
      fields[el.dataset.el] = {
        x: parseInt(el.style.left) || 0, y: parseInt(el.style.top) || 0,
        fontSize: parseInt(cs.fontSize) || 11, bold: cs.fontWeight === '700' || cs.fontWeight === 'bold',
      };
    });
    const li = canvas.querySelector('.pp-lineitems');
    const columns = [...canvas.querySelectorAll('.pp-lineitems thead th')].map((th) => ({
      key: th.dataset.col, visible: true, width: parseInt(th.style.width) || 60,
    }));
    // hidden columns (tracked via a data-hidden set on the lineitems block)
    (li.dataset.hidden || '').split(',').filter(Boolean).forEach((k) =>
      columns.push({ key: k, visible: false, width: 60 }));
    const lics = getComputedStyle(li);
    return {
      page: { fontFamily: getComputedStyle(document.body).fontFamily },
      fields,
      lineItems: {
        x: parseInt(li.style.left) || 0, y: parseInt(li.style.top) || 0,
        width: parseInt(li.style.width) || 714,
        fontSize: parseInt(lics.fontSize) || 10,
        bold: lics.fontWeight === '700' || lics.fontWeight === 'bold',
        columns,
      },
    };
  }

  saveBtn.addEventListener('click', async () => {
    const resp = await fetch('/sales-invoices/print-layout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify(collect()),
    });
    if (resp.ok) {
      const flag = document.createElement('span');
      flag.id = 'layoutSavedFlag'; flag.style.display = 'none';
      document.body.appendChild(flag);
      saveBtn.textContent = 'Saved ✓';
      setTimeout(() => { saveBtn.textContent = 'Save Layout'; }, 1500);
    } else {
      saveBtn.textContent = 'Save failed';
    }
  });
})();
```

```css
/* app/static/css/sv_preprinted_designer.css */
.pp-canvas.pp-editing .pp-el { outline: 1px dashed #2e7d32; cursor: move; }
.pp-canvas.pp-editing .pp-el:hover { outline: 2px solid #2e7d32; background: rgba(46,125,50,.05); }
.pp-canvas.pp-editing { outline: 1px solid #bbb; }
```

- [ ] **Step 4: Run to verify green**

Run: `python -m playwright install chromium` (once), then `pytest tests/e2e/test_sv_preprinted_designer.py -q`
Expected: PASS — drag moves the element and the new left persists after reload.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/sv_preprinted_designer.js app/static/css/sv_preprinted_designer.css tests/e2e/test_sv_preprinted_designer.py tests/e2e/conftest.py
git commit -m "feat(si-preprinted): drag-to-position editor + save/persist (SI-P-71 Task 4)"
```

---

### Task 5: Column reorder + show/hide

**Files:**
- Modify: `app/static/js/sv_preprinted_designer.js`, `app/static/css/sv_preprinted_designer.css`
- Test: extend `tests/e2e/test_sv_preprinted_designer.py`

**Behavior:** In edit mode, the line-items header shows a small per-column control strip: each column header is drag-reorderable left/right (pointer drag swapping `<th>`/matching `<td>` order in the DOM), and each has a show/hide checkbox. Hidden columns are removed from the rendered table and recorded on `li.dataset.hidden` so `collect()` serializes them `visible:false`. Reordering updates DOM order, which `collect()` reads.

- [ ] **Step 1: Failing e2e test**

```python
def test_hide_column_persists(logged_in_page, e2e_server, app, si_invoice_id):
    _seed_preprinted(app)
    page = logged_in_page
    page.goto(f'{e2e_server}/sales-invoices/{si_invoice_id}/print')
    page.click('#editLayoutBtn')
    page.uncheck('[data-coltoggle="uom"]')          # hide UOM
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag')
    with app.app_context():
        layout = json.loads(AppSettings.get_setting('sv_preprinted_layout'))
    uom = next(c for c in layout['lineItems']['columns'] if c['key'] == 'uom')
    assert uom['visible'] is False
```

- [ ] **Step 2: Run to verify fail** — `[data-coltoggle="uom"]` absent. FAIL.
- [ ] **Step 3: Implement** the column control strip + reorder handlers in the JS (render checkboxes into a `.pp-col-controls` bar shown only in edit mode; wire hide→remove `<th>`/`<td data-col=key>` and add key to `li.dataset.hidden`; show→re-insert; drag headers to reorder). Update `collect()` already reads DOM order + `dataset.hidden`.
- [ ] **Step 4: Run to verify green.**
- [ ] **Step 5: Commit** `feat(si-preprinted): column reorder + show/hide (SI-P-71 Task 5)`.

---

### Task 6: Font controls — per-element size + bold, page font-family

**Files:**
- Modify: `app/static/js/sv_preprinted_designer.js`, `app/static/css/sv_preprinted_designer.css`
- Test: extend `tests/e2e/test_sv_preprinted_designer.py`

**Behavior:** Clicking a `.pp-el` in edit mode selects it and shows a small floating toolbar with a font-size stepper (−/＋, writes `el.style.fontSize`) and a **B** bold toggle (writes `el.style.fontWeight`). A page-level `<select>` in the edit bar lists `ALLOWED_FONTS` and sets `document.body.style.fontFamily`. `collect()` already reads computed font-size/weight/family, so no serialize change. The font-family `<select>` options must exactly match `ALLOWED_FONTS` server-side (pass them into the template from the view as `ALLOWED_FONTS`).

- [ ] **Step 1: Failing e2e test**

```python
def test_bold_and_font_persist(logged_in_page, e2e_server, app, si_invoice_id):
    _seed_preprinted(app)
    page = logged_in_page
    page.goto(f'{e2e_server}/sales-invoices/{si_invoice_id}/print')
    page.click('#editLayoutBtn')
    page.click('[data-el="terms"]')                 # select element
    page.click('#ppBoldBtn')                        # toggle bold on
    page.select_option('#ppFontFamily', 'Georgia, serif')
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag')
    with app.app_context():
        layout = json.loads(AppSettings.get_setting('sv_preprinted_layout'))
    assert layout['fields']['terms']['bold'] is True
    assert layout['page']['fontFamily'] == 'Georgia, serif'
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** selection + floating toolbar (size stepper, bold) + page font `<select>` populated from `ALLOWED_FONTS` (pass from view). Add selection CSS.
- [ ] **Step 4: Run to verify green.**
- [ ] **Step 5: Commit** `feat(si-preprinted): per-element font-size/bold + page font-family (SI-P-71 Task 6)`.

---

### Task 7: Wiring, cache-busters, docs

**Files:**
- Modify: `docs/superpowers/plans/INDEX.md`, `docs/ROADMAP.md`, `.claude/regression-map.json`
- Verify: cache-buster `?v=N` on the two new static assets is present (they start at `?v=1`).

- [ ] **Step 1:** Add the two new static files to `.claude/regression-map.json` under the SI print blast-radius so a future change re-runs these e2e tests. Add a row to `docs/superpowers/plans/INDEX.md` (this plan, status Done). Note the feature in `docs/ROADMAP.md` under R-01 Sales / the pre-printed rebuild.
- [ ] **Step 2:** Run the full SI marker set + the new e2e: `pytest -m sales_invoices -q` then `pytest -m e2e -q`. Expected: green.
- [ ] **Step 3: Commit** `chore(si-preprinted): regression-map + docs for the layout designer (SI-P-71 Task 7)`.

---

## Notes / risks for the implementer

- **CSRF:** the save is a JSON `fetch`; production needs the `X-CSRFToken` header (wired from the `<meta>` tag). Testing config disables CSRF, so pytest integration tests don't send it — but the **e2e** server runs a real config; confirm `tests/e2e/_serve.py`'s config leaves CSRF satisfiable (the meta token + header is included). If the e2e config enables CSRF and the token isn't accepted for cross-fetch, either exempt this one route via `csrf.exempt` **and** keep the admin gate (the admin session is the real guard) or ensure the header path works. Decide at Task 2/4; do not weaken the admin gate.
- **No Python hot-reload:** after editing `views.py`/`preprinted_layout.py`, restart the dev server before browser-checking (templates + static reload live; `.py` does not).
- **`sv-preprinted` marker:** Task 3 replaces the old template; update the one existing assertion in `test_sv_print_form.py` that greps `sv-preprinted` to the new `pp-canvas` marker (keep the `sv-header` absent check).
- **Ripple:** `print.html` (the non-pre-printed form) is untouched. `sv_print_form` values `current`/`hidden` behave exactly as before; only `preprinted` renders the new canvas.
- **YAGNI:** one SI layout, company-wide. No per-branch/per-user layouts, no multi-doc — those are future and out of scope.
```
