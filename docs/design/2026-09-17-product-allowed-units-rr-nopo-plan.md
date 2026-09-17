# Per-Product Allowed Units (no-PO Receiving) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin curate, per product, the set of units of measure acceptable on no-PO ("Add Item Without PO") receiving-report lines, and enforce that set both in the picker and on the server.

**Architecture:** A new many-to-many association table `product_allowed_units` links `products` to `units_of_measure`. `Product` gains an `allowed_units` relationship and two resolver helpers. The product create/edit form gets a multi-select for the set. Receiving-report no-PO lines are constrained by a server guard in `_parse_rr_lines` (authoritative) and a picker filter in the RR form JS (UX). The feature is opt-in: a product with an empty set is unconstrained (today's behavior), and the product's default unit is always allowed.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, SQLite, WTForms, hand-written Alembic migrations, pytest.

**Spec:** `docs/design/2026-09-17-product-allowed-units-rr-nopo-design.md`

## Global Constraints

- **Enforcement scope is no-PO RR lines ONLY.** Do not touch PO-backed RR lines or any other document (PO, PR, quotations, SI, SO, memos, AP/CDV/CRV).
- **Opt-in:** an empty allowed set means *unconstrained* — any active unit is accepted. No backfill of existing products.
- **Default always allowed:** a blank unit (→ product default) always passes, and `default_unit_of_measure_id` is an implicit member of the set.
- **Migrations are hand-written.** `Migrate()` runs without `render_as_batch`. `create_table` needs no batch wrapper. **Name every FK/PK/unique constraint explicitly.** Verify the migration against a **copy of a real database**, never a `create_all()` test DB.
- **Current alembic head is `apamd_0001`** — the new migration's `down_revision` is `'apamd_0001'`.
- **Audit** product changes via `to_dict()` (which will include `allowed_unit_ids`); verify the audit log through the real HTTP route in a CRUD test.
- **Register any new pytest module marker** in `pytest.ini` (none new is expected; reuse `integration`).

---

### Task 1: Association table, ORM relationship, resolver helpers + migration

**Files:**
- Modify: `app/products/models.py` (add association table, relationship, helpers, extend `to_dict`)
- Create: `migrations/versions/prodau_0001_product_allowed_units.py`
- Test: `tests/integration/test_product_allowed_units.py`

**Interfaces:**
- Produces:
  - Module-level `product_allowed_units` (`db.Table`) in `app/products/models.py`.
  - `Product.allowed_units` — relationship to `UnitOfMeasure` (list).
  - `Product.allowed_unit_ids() -> set[int]` — the associated unit ids (empty set = unconstrained).
  - `Product.unit_allowed(uom_id) -> bool` — True if `uom_id` is falsy, or the set is empty, or `uom_id` is in the set, or `uom_id == self.default_unit_of_measure_id`.
  - `Product.to_dict()` gains key `'allowed_unit_ids'` → `sorted(list[int])`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_product_allowed_units.py`:

```python
"""Per-product allowed-units resolver (prodau_0001).

Empty set = unconstrained (opt-in). A curated set constrains, but the product's
default unit is always allowed, and a blank unit (falls back to default) always passes.
"""
import pytest

from app import db
from app.products.models import Product
from app.units_of_measure.models import UnitOfMeasure

pytestmark = [pytest.mark.integration]


def _uom(code, name):
    u = UnitOfMeasure(code=code, name=name, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def test_empty_set_allows_any_unit(db_session):
    kg = _uom('KG', 'Kilogram')
    p = Product(name='Unconstrained', is_active=True)
    db.session.add(p)
    db.session.commit()
    assert p.allowed_unit_ids() == set()
    assert p.unit_allowed(kg.id) is True      # unconstrained
    assert p.unit_allowed(None) is True        # blank -> default


def test_curated_set_constrains_but_default_always_allowed(db_session):
    box = _uom('BOX', 'Box')
    kg = _uom('KG', 'Kilogram')
    piece = _uom('PC', 'Piece')
    p = Product(name='Constrained', default_unit_of_measure_id=piece.id, is_active=True)
    p.allowed_units = [box]
    db.session.add(p)
    db.session.commit()
    assert p.allowed_unit_ids() == {box.id}
    assert p.unit_allowed(box.id) is True       # in the set
    assert p.unit_allowed(kg.id) is False       # not in set, not default
    assert p.unit_allowed(piece.id) is True     # default always allowed
    assert p.unit_allowed(None) is True         # blank -> default
    assert p.to_dict()['allowed_unit_ids'] == [box.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_product_allowed_units.py -q`
Expected: FAIL — `AttributeError: 'Product' object has no attribute 'allowed_units'` (or `allowed_unit_ids`).

- [ ] **Step 3: Add the association table, relationship, helpers, and to_dict key**

In `app/products/models.py`, add the association table just above `class Product` (after the `COSTING_METHODS` line):

```python
# Per-product allowed units for no-PO receiving lines (prodau_0001). Opt-in:
# an empty set means "any active unit". Surrogate id PK + a unique (product,
# unit) pair — a proper relationship, mirroring how user<->branches is modelled.
product_allowed_units = db.Table(
    'product_allowed_units',
    db.Column('id', db.Integer, primary_key=True),
    db.Column('product_id', db.Integer,
              db.ForeignKey('products.id'), nullable=False),
    db.Column('unit_of_measure_id', db.Integer,
              db.ForeignKey('units_of_measure.id'), nullable=False),
    db.UniqueConstraint('product_id', 'unit_of_measure_id',
                        name='uq_product_allowed_units_product_unit'),
)
```

Inside `class Product`, add the relationship next to the other relationships (after the `created_by` relationship line):

```python
    allowed_units = db.relationship('UnitOfMeasure', secondary=product_allowed_units)
```

Add the two helper methods (after `__repr__`, before `to_dict`):

```python
    def allowed_unit_ids(self):
        """The set of unit ids curated for no-PO receiving. Empty = unconstrained."""
        return {u.id for u in self.allowed_units}

    def unit_allowed(self, uom_id):
        """Whether uom_id may be used on a no-PO receiving line for this product.

        A blank unit (falls back to the product default) always passes. An empty
        curated set is unconstrained (opt-in). Otherwise the unit must be in the
        set, or be the product's default (always implicitly allowed).
        """
        if not uom_id:
            return True
        ids = self.allowed_unit_ids()
        if not ids:
            return True
        return uom_id in ids or uom_id == self.default_unit_of_measure_id
```

In `Product.to_dict()`, add this key (place it right after the `'default_uom_code'` entry):

```python
            'allowed_unit_ids': sorted(self.allowed_unit_ids()),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_product_allowed_units.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the migration**

Create `migrations/versions/prodau_0001_product_allowed_units.py`:

```python
"""Per-product allowed units for no-PO receiving lines.

Purely ADDITIVE — one new association table, no existing table altered.
create_table needs no batch wrapper; all constraints are NAMED so a later batch
rebuild can reproduce them.

Revision ID: prodau_0001
Revises: apamd_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'prodau_0001'
down_revision = 'apamd_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'product_allowed_units',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('unit_of_measure_id', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_product_allowed_units'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'],
                                name='fk_product_allowed_units_product'),
        sa.ForeignKeyConstraint(['unit_of_measure_id'], ['units_of_measure.id'],
                                name='fk_product_allowed_units_unit'),
        sa.UniqueConstraint('product_id', 'unit_of_measure_id',
                            name='uq_product_allowed_units_product_unit'),
    )
    op.create_index('ix_product_allowed_units_product_id',
                    'product_allowed_units', ['product_id'])


def downgrade():
    op.drop_index('ix_product_allowed_units_product_id',
                  table_name='product_allowed_units')
    op.drop_table('product_allowed_units')
```

- [ ] **Step 6: Verify the migration against a COPY of a real database**

Run (from `cas/`, using the Bash tool):

```bash
cp instance/philgen.db instance/_verify_prodau.db
SECRET_KEY=verify SQLALCHEMY_DATABASE_URI="sqlite:///_verify_prodau.db" flask db upgrade
SECRET_KEY=verify SQLALCHEMY_DATABASE_URI="sqlite:///_verify_prodau.db" flask db current
python -c "import sqlite3; c=sqlite3.connect('instance/_verify_prodau.db'); print(c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='product_allowed_units'\").fetchone()); print([r[1] for r in c.execute('PRAGMA table_info(product_allowed_units)')])"
SECRET_KEY=verify SQLALCHEMY_DATABASE_URI="sqlite:///_verify_prodau.db" flask db downgrade -1
rm instance/_verify_prodau.db
```

Expected: `flask db current` prints `prodau_0001 (head)`; the sqlite check prints `('product_allowed_units',)` and `['id', 'product_id', 'unit_of_measure_id']`; the downgrade succeeds; the temp file is removed.

- [ ] **Step 7: Commit**

```bash
git add app/products/models.py migrations/versions/prodau_0001_product_allowed_units.py tests/integration/test_product_allowed_units.py
git commit -m "feat(products): product_allowed_units table + allowed_units/unit_allowed helpers"
```

---

### Task 2: Product form field, view persistence, template, and CRUD/audit tests

**Files:**
- Modify: `app/products/forms.py` (add `allowed_unit_ids` field)
- Modify: `app/products/views.py` (populate choices, persist set on create/edit, prefill on edit GET, import `UnitOfMeasure`)
- Modify: `app/products/templates/products/form.html` (multi-select + hint)
- Test: `tests/integration/test_products_crud.py` (append tests)

**Interfaces:**
- Consumes: `Product.allowed_units`, `Product.allowed_unit_ids()`, `Product.to_dict()['allowed_unit_ids']` from Task 1.
- Produces: `ProductForm.allowed_unit_ids` — `SelectMultipleField(coerce=int)`, list of int unit ids.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_products_crud.py` (the file already has `_login`, `products_module_enabled`, and imports `db` and `Product`; add `from app.units_of_measure.models import UnitOfMeasure` at the top if not present, and `import json`):

```python
def test_create_persists_allowed_units(client, db_session, admin_user, main_branch,
                                       products_module_enabled):
    box = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    kg = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
    db.session.add_all([box, kg]); db.session.commit()
    _login(client, admin_user, main_branch)
    client.post('/products/create', data={
        'name': 'Constrained', 'description': '',
        'default_unit_of_measure_id': '', 'default_unit_price': '',
        'default_account_id': '', 'category_id': '', 'standard_cost': '',
        'is_active': '1',
        'allowed_unit_ids': [str(box.id), str(kg.id)],
    }, follow_redirects=True)
    p = Product.query.filter_by(name='Constrained').first()
    assert p is not None
    assert p.allowed_unit_ids() == {box.id, kg.id}


def test_edit_replaces_then_clears_allowed_units(client, db_session, admin_user,
                                                 main_branch, products_module_enabled):
    box = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    kg = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
    db.session.add_all([box, kg]); db.session.commit()
    p = Product(name='EditSet', is_active=True)
    p.allowed_units = [box, kg]
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    # Narrow to just BOX
    client.post(f'/products/{p.id}/edit', data={
        'name': 'EditSet', 'description': '',
        'default_unit_of_measure_id': '', 'default_unit_price': '',
        'default_account_id': '', 'category_id': '', 'standard_cost': '',
        'is_active': '1', 'allowed_unit_ids': [str(box.id)],
    }, follow_redirects=True)
    db.session.refresh(p)
    assert p.allowed_unit_ids() == {box.id}
    # Clear entirely (omit the field)
    client.post(f'/products/{p.id}/edit', data={
        'name': 'EditSet', 'description': '',
        'default_unit_of_measure_id': '', 'default_unit_price': '',
        'default_account_id': '', 'category_id': '', 'standard_cost': '',
        'is_active': '1',
    }, follow_redirects=True)
    db.session.refresh(p)
    assert p.allowed_unit_ids() == set()


def test_allowed_units_recorded_in_create_audit(client, db_session, admin_user,
                                                main_branch, products_module_enabled):
    from app.audit.models import AuditLog
    box = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    db.session.add(box); db.session.commit()
    _login(client, admin_user, main_branch)
    client.post('/products/create', data={
        'name': 'AuditedSet', 'description': '',
        'default_unit_of_measure_id': '', 'default_unit_price': '',
        'default_account_id': '', 'category_id': '', 'standard_cost': '',
        'is_active': '1', 'allowed_unit_ids': [str(box.id)],
    }, follow_redirects=True)
    p = Product.query.filter_by(name='AuditedSet').first()
    log = (AuditLog.query.filter_by(module='products', action='create', record_id=p.id)
           .order_by(AuditLog.id.desc()).first())
    assert log is not None
    assert json.loads(log.new_values)['allowed_unit_ids'] == [box.id]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/integration/test_products_crud.py -q -k "allowed_units"`
Expected: FAIL — the form ignores `allowed_unit_ids`, so the set is empty / the audit key is missing.

- [ ] **Step 3: Add the form field**

In `app/products/forms.py`, add `SelectMultipleField` to the wtforms import line, and add the field after `default_unit_of_measure_id`:

```python
from wtforms import (StringField, TextAreaField, SelectField, DecimalField,
                     BooleanField, SelectMultipleField)
```

```python
    # Curated per-product allow-list for NO-PO receiving lines. Empty = any active
    # unit (opt-in). coerce=int; choices are active UOMs, populated in the view.
    allowed_unit_ids = SelectMultipleField('Allowed Units (no-PO receiving)',
                                           coerce=int, validators=[Optional()])
```

- [ ] **Step 4: Populate choices and persist the set in the view**

In `app/products/views.py`:

Add the import near the top:

```python
from app.units_of_measure.models import UnitOfMeasure
```

In `_populate_choices`, after the `default_unit_of_measure_id.choices` assignment, add:

```python
    form.allowed_unit_ids.choices = [(u.id, f'{u.code} — {u.name}') for u in units]
```

In `create()`, replace the `db.session.add(p)` / `db.session.commit()` pair with:

```python
        db.session.add(p)
        if form.allowed_unit_ids.data:
            p.allowed_units = (UnitOfMeasure.query
                               .filter(UnitOfMeasure.id.in_(form.allowed_unit_ids.data))
                               .all())
        db.session.commit()
```

In `edit()`, in the `request.method == 'GET'` block, add:

```python
        form.allowed_unit_ids.data = sorted(p.allowed_unit_ids())
```

In `edit()`, in the POST block just before `db.session.commit()`, add:

```python
        p.allowed_units = (UnitOfMeasure.query
                           .filter(UnitOfMeasure.id.in_(form.allowed_unit_ids.data)).all()
                           if form.allowed_unit_ids.data else [])
```

(The audit is automatic: `create` logs `p.to_dict()` after commit, and `edit` captures `old = p.to_dict()` before changes and `p.to_dict()` after — both now include `allowed_unit_ids`.)

- [ ] **Step 5: Add the multi-select to the template**

In `app/products/templates/products/form.html`, immediately after the form-group that renders `default_unit_of_measure_id` (the `{{ render_field(form.default_unit_of_measure_id) }}` group, around line 36), add:

```html
            <div class="form-group">
                {{ form.allowed_unit_ids.label }}
                {{ form.allowed_unit_ids(class='form-control', multiple=true, size=6, style='height:auto;') }}
                <div class="form-hint">Leave empty to allow any active unit. Selecting units limits no-PO receiving to those units (the default unit is always allowed). Hold Ctrl (Cmd on Mac) to select multiple.</div>
            </div>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_products_crud.py -q`
Expected: PASS (all, including the 3 new tests and the pre-existing suite).

- [ ] **Step 7: Commit**

```bash
git add app/products/forms.py app/products/views.py app/products/templates/products/form.html tests/integration/test_products_crud.py
git commit -m "feat(products): admin can curate allowed units per product (form + persistence + audit)"
```

---

### Task 3: RR server enforcement + payload

**Files:**
- Modify: `app/receiving_reports/views.py` (`_direct_products_payload` adds `allowed_unit_ids`; `_parse_rr_lines` direct-line branch adds the allowed-set guard)
- Test: `tests/integration/test_rr_allowed_units.py`

**Interfaces:**
- Consumes: `Product.unit_allowed(uom_id)`, `Product.allowed_units`, `Product.default_unit_of_measure` from Task 1.
- Produces: each dict from `_direct_products_payload()` gains `'allowed_unit_ids': sorted(list[int])`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_rr_allowed_units.py`:

```python
"""No-PO receiving lines are constrained to a product's curated allowed units
(prodau_0001). Opt-in: no set => any active unit. Default always allowed. The
server guard is authoritative — _create_via_form posts through the real route,
which is the seam a raw POST reaches.
"""
import pytest
from decimal import Decimal

from app import db
from app.products.models import Product
from app.receiving_reports.models import ReceivingReport
from app.units_of_measure.models import UnitOfMeasure
from tests.integration.test_rr_direct_receipt import (  # noqa: F401
    _create_via_form, vendor)
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _units():
    box = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    kg = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
    pc = UnitOfMeasure(code='PC', name='Piece', is_active=True)
    db.session.add_all([box, kg, pc]); db.session.commit()
    return box, kg, pc


def test_unit_in_allowed_set_is_accepted(client, db_session, main_branch, vendor,
                                         admin_user, rr_enabled):
    box, kg, pc = _units()
    p = Product(name='Boxed', track_inventory=False, is_active=True,
                default_unit_of_measure_id=pc.id)
    p.allowed_units = [box]
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    _, rr = _create_via_form(client, vendor, [{'product_id': p.id,
                                               'received_quantity': '2',
                                               'unit_of_measure_id': box.id}])
    assert rr is not None
    assert rr.line_items[0].unit_of_measure_id == box.id


def test_unit_outside_allowed_set_is_rejected(client, db_session, main_branch, vendor,
                                              admin_user, rr_enabled):
    box, kg, pc = _units()
    p = Product(name='Boxed2', track_inventory=False, is_active=True,
                default_unit_of_measure_id=pc.id)
    p.allowed_units = [box]
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    resp, rr = _create_via_form(client, vendor, [{'product_id': p.id,
                                                  'received_quantity': '2',
                                                  'unit_of_measure_id': kg.id}])
    assert rr is None
    assert 'not an allowed unit' in resp.get_data(as_text=True)


def test_blank_unit_falls_back_to_default_even_if_default_not_listed(
        client, db_session, main_branch, vendor, admin_user, rr_enabled):
    box, kg, pc = _units()
    p = Product(name='Boxed3', track_inventory=False, is_active=True,
                default_unit_of_measure_id=pc.id)
    p.allowed_units = [box]           # default (PC) intentionally NOT in the set
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    _, rr = _create_via_form(client, vendor, [{'product_id': p.id,
                                               'received_quantity': '2'}])
    assert rr is not None
    assert rr.line_items[0].unit_of_measure_id is None


def test_empty_set_accepts_any_active_unit(client, db_session, main_branch, vendor,
                                           admin_user, rr_enabled):
    box, kg, pc = _units()
    p = Product(name='Unconstrained', track_inventory=False, is_active=True)
    db.session.add(p); db.session.commit()      # no allowed_units
    _login(client, admin_user, main_branch)
    _, rr = _create_via_form(client, vendor, [{'product_id': p.id,
                                               'received_quantity': '2',
                                               'unit_of_measure_id': kg.id}])
    assert rr is not None
    assert rr.line_items[0].unit_of_measure_id == kg.id


def test_payload_includes_allowed_unit_ids(db_session, app):
    box, kg, pc = _units()
    p = Product(name='PayloadProd', track_inventory=False, is_active=True)
    p.allowed_units = [box]
    db.session.add(p); db.session.commit()
    from app.receiving_reports.views import _direct_products_payload
    with app.test_request_context():
        rows = _direct_products_payload()
    row = next(r for r in rows if r['product_id'] == p.id)
    assert row['allowed_unit_ids'] == [box.id]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/integration/test_rr_allowed_units.py -q`
Expected: FAIL — the out-of-set line is currently accepted (`rr is None` assertion fails), and `_direct_products_payload` has no `allowed_unit_ids` key.

- [ ] **Step 3: Add `allowed_unit_ids` to the RR payload**

In `app/receiving_reports/views.py`, in `_direct_products_payload()`, extend the returned dict:

```python
    return [{'product_id': p.id, 'product_name': p.name,
             'uom': (p.default_unit_of_measure.code if p.default_unit_of_measure else ''),
             'tracked': bool(p.track_inventory),
             'allowed_unit_ids': sorted(p.allowed_unit_ids())}
            for p in rows]
```

- [ ] **Step 4: Add the server guard in `_parse_rr_lines`**

In `app/receiving_reports/views.py`, in `_parse_rr_lines`, inside the `if product_id:` branch, immediately **after** the block that validates `uom` exists and is active (right after the `if uom is None or not uom.is_active:` raise, still inside `if uom_id:`), add:

```python
                if not product.unit_allowed(uom_id):
                    allowed = sorted(
                        {u.code for u in product.allowed_units}
                        | ({product.default_unit_of_measure.code}
                           if product.default_unit_of_measure else set()))
                    raise ValueError(
                        f'Line {position}: {uom.code} is not an allowed unit for '
                        f'{product.name}. Choose one of: {", ".join(allowed)}.')
```

(`uom` and `uom_id` are already defined in this branch. A blank `uom_id` never reaches here — the `else: uom_id = None` path — and `unit_allowed(None)` is True anyway, so the default fallback is preserved.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_rr_allowed_units.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Run the wider RR suite to confirm no regression**

Run: `python -m pytest tests/integration/test_rr_direct_receipt.py tests/integration/test_rr_form_render.py -q`
Expected: PASS (unchanged behavior for unconstrained products).

- [ ] **Step 7: Commit**

```bash
git add app/receiving_reports/views.py tests/integration/test_rr_allowed_units.py
git commit -m "feat(rr): enforce per-product allowed units on no-PO lines (server guard + payload)"
```

---

### Task 4: RR picker UI filter

**Files:**
- Modify: `app/receiving_reports/templates/receiving_reports/form.html` (filter the no-PO `directUom` picker to the selected product's allowed set)
- Test: `tests/integration/test_rr_form_render.py` (assert the allowed-units data reaches the page)

**Interfaces:**
- Consumes: `DIRECT_INDEX[product_id].allowed_unit_ids` (added to the payload in Task 3), `UNITS`, `UNIT_INDEX`, the `directUom` select and its Choices instance `uomChoices`.

**Note:** The RR form JS is exercised in tests by a DOM shim that throws on `fetch`/`Choices`/modals, so the *filtering behavior itself* is verified manually in the browser; the automated test asserts the data is present on the page (the picker cannot filter to a set it never received). Keep the JS defensive: any failure falls back to showing all active units.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_rr_form_render.py` (reuse that file's existing fixtures for logging in and enabling RR; mirror an existing render test's setup for `client`, `admin_user`, `main_branch`, and vendor selection):

```python
def test_direct_products_payload_carries_allowed_units_to_form(client, db_session,
                                                               main_branch, admin_user,
                                                               rr_enabled):
    from app.products.models import Product
    from app.units_of_measure.models import UnitOfMeasure
    from tests.integration.test_rr_submit import _login
    box = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    db.session.add(box); db.session.commit()
    p = Product(name='PickerProd', track_inventory=False, is_active=True)
    p.allowed_units = [box]
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    resp = client.get('/receiving-reports/create')
    body = resp.get_data(as_text=True)
    assert 'allowed_unit_ids' in body
    assert str(box.id) in body
```

(If `test_rr_form_render.py` already imports `db`/`_login`/`rr_enabled`, drop the redundant imports. Match the module's existing fixture names; if its render tests use a different login helper, use that one.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_rr_form_render.py -q -k allowed_units`
Expected: FAIL only if Task 3 is not yet merged; if Task 3 is merged the payload already carries the key, so this test may PASS immediately — in that case treat Step 1–2 as a guard test and proceed to the JS filter (the render assertion still documents the contract).

- [ ] **Step 3: Add the picker filter to the RR form JS**

In `app/receiving_reports/templates/receiving_reports/form.html`, in the no-PO picker IIFE (the block that builds `directProduct`/`directUom`), add a filter function and wire it to the product `change` event. The product select's change handler is currently `sel.addEventListener('change', refreshWarning);` — add a second handler.

Add this function inside that IIFE (near `refreshWarning`):

```javascript
    // Limit the unit picker to the product's curated allowed set (+ its default).
    // Empty set => show all active units (today's behavior). Defensive: any error
    // falls back to the full list, since the server is the real guard.
    function filterUomForProduct() {
      try {
        const prod = DIRECT_INDEX[parseInt(sel.value, 10)];
        const allowed = (prod && prod.allowed_unit_ids) ? prod.allowed_unit_ids : [];
        let units = UNITS || [];
        if (allowed.length) {
          const ok = new Set(allowed);
          // The product's default unit is always allowed even if not in the set.
          const rows = (window.DIRECT_DEFAULT_UOM || {});
          units = units.filter(function (u) { return ok.has(u.id); });
        }
        const opts = units.map(function (u) {
          return { value: String(u.id), label: u.code + ' — ' + u.name };
        });
        opts.unshift({ value: '', label: '— Use product default —' });
        if (uomChoices) {
          uomChoices.clearChoices();
          uomChoices.setChoices(opts, 'value', 'label', true);
          uomChoices.setChoiceByValue('');
        } else {
          uomSel.innerHTML = opts.map(function (o) {
            return '<option value="' + o.value + '">' + o.label + '</option>';
          }).join('');
          uomSel.value = '';
        }
      } catch (e) { /* fall back to the full list already in the DOM */ }
    }
```

Wire it after the existing change handler:

```javascript
    sel.addEventListener('change', filterUomForProduct);
```

And call `filterUomForProduct()` once inside the modal-open handler (`btn.addEventListener('click', ...)`), right after the existing `uomChoices.setChoiceByValue('')` / `uomSel.value = ''` reset, so the picker opens already filtered for the currently selected product.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_rr_form_render.py -q`
Expected: PASS (including the new assertion).

- [ ] **Step 5: Manual verification (browser)**

Start the app (`.\cas.ps1 philgen`), open Receiving Reports → Enter → pick a vendor → "Add Item Without PO", select a product that has a curated allowed set, and confirm the unit dropdown lists only that set plus "— Use product default —". Select a product with no set and confirm all active units appear. (This is the only check for the JS behavior; the DOM shim can't exercise it.)

- [ ] **Step 6: Commit**

```bash
git add app/receiving_reports/templates/receiving_reports/form.html tests/integration/test_rr_form_render.py
git commit -m "feat(rr): filter no-PO unit picker to the product's allowed units"
```

---

## Self-Review

**Spec coverage:**
- Data model (association table, relationship, `allowed_unit_ids`/`unit_allowed`, `to_dict`) → Task 1. ✅
- Migration `prodau_0001`, named constraints, verified against a real-DB copy → Task 1 Steps 5–6. ✅
- Admin UI (form multi-select + hint), persistence, audit → Task 2. ✅
- RR server guard + payload → Task 3. ✅
- RR picker UI filter → Task 4. ✅
- Opt-in / default-always-allowed semantics → covered by `unit_allowed` (Task 1) and exercised in Tasks 1 & 3. ✅
- Edge cases: inactive unit (existing active-check precedes the new guard, Task 3 Step 4 placement); raw POST bypass (Task 3 tests use the real route); default always allowed (Task 1 & Task 3 blank-unit test). ✅

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to"/"write tests for the above" — every code and test step contains actual content.

**Type consistency:** `allowed_unit_ids()` returns `set[int]` everywhere; `to_dict()['allowed_unit_ids']` is `sorted(list[int])`; the form field coerces to `int` and its choices use int keys; `unit_allowed(uom_id)` takes an int-or-falsy and is called with an int in `_parse_rr_lines` and in the model tests. Consistent.

---

## Execution Handoff

Plan complete and saved to `docs/design/2026-09-17-product-allowed-units-rr-nopo-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
