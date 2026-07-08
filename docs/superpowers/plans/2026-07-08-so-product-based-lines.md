# Sales Order — Product-Based Lines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Sales Order a product-based operational document — each line is a required Product (no free-text Description), and the `sales_orders` module becomes optional and gated on the Products module.

**Architecture:** Four independent tasks: (1) flip the `sales_orders` module registry entry to optional + Products-dependent and keep it per-user grantable; (2) hard-drop the `SalesOrderItem.description` column via a hand-written batch migration, updating the model/serializer/parser/tests that reference it; (3) add a server-side guard rejecting any line with no product; (4) rewrite the SO templates to a product-first UI and delete the orphan `view.html`.

**Tech Stack:** Flask + SQLAlchemy + SQLite; Flask-Migrate/Alembic (hand-written batch migrations, `render_as_batch` OFF); pytest (markers in `pytest.ini`; run single-threaded with `-p no:cov` for speed).

## Global Constraints

- **Model change requires the drop-column migration in the SAME task** — never leave the model and schema out of sync. Migrations are HAND-WRITTEN with `op.batch_alter_table(...)`; verify on a COPY of a real DB (`cas.db`), not a conftest `create_all()`.
- **Product-required is enforced by a server-side guard, NOT a `nullable=False` column** — pre-existing draft rows must stay readable.
- **`sales_orders` becomes `optional: True, depends_on: ['products'], default_enabled: False, per_user: True`.** Because `products depends_on ['units_of_measure']`, enabling SO transitively requires Products + UoM.
- **A `ValueError` raised for a validation failure is flashed verbatim; only the broad `except Exception` is genericized** (`feedback-genericize-flash-keep-valueerror`).
- **Peso glyph never rendered; em-dash uses the literal `—` glyph** (already applied to SO templates on the parent branch).
- Run tests with the project venv: `venv/Scripts/python.exe -m pytest ... -p no:cov`.

---

### Task 1: Gate the Sales Orders module on Products

Flip the registry entry and keep SO in the per-user permission grid (a bare `optional: True` would drop it from `all_permission_keys()` → SO becomes admin-only — the documented revert-cause).

**Files:**
- Modify: `app/users/module_access.py` (the `sales_orders` registry entry, ~line 17-20; `all_permission_keys()`, ~line 184)
- Test: `tests/integration/test_module_enablement.py` (add cases)

**Interfaces:**
- Produces: `sales_orders` registry entry with `optional=True, depends_on=['products'], default_enabled=False, per_user=True`; `all_permission_keys()` now includes optional-but-per_user keys.

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_module_enablement.py`:

```python
def test_sales_orders_requires_products_to_enable():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('sales_orders', True, enabled_keys=[])
    assert ok is False and 'products' in reason
    ok2, _ = can_toggle('sales_orders', True, enabled_keys=['units_of_measure', 'products'])
    assert ok2 is True


def test_sales_orders_stays_in_per_user_grid_though_optional():
    from app.users.module_access import all_permission_keys, MODULE_REGISTRY
    entry = next(m for m in MODULE_REGISTRY if m['key'] == 'sales_orders')
    assert entry['optional'] is True and entry.get('per_user') is True
    assert 'sales_orders' in all_permission_keys()   # not dropped to admin-only


def test_sales_orders_disabled_by_default():
    from app.users.module_access import module_enabled
    assert module_enabled('sales_orders') is False   # default_enabled False, no override
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_module_enablement.py -k sales_orders -p no:cov -v`
Expected: FAIL — `sales_orders` is currently `optional: False`, so `can_toggle` returns `(True, '')`, `per_user` is absent, and `module_enabled` returns True.

- [ ] **Step 3: Flip the registry entry**

In `app/users/module_access.py`, replace the `sales_orders` entry:

```python
    {'key': 'sales_orders', 'label': 'Sales Orders', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': ['products'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('sales_orders.',)},
```

- [ ] **Step 4: Decouple `all_permission_keys()` so per-user optionals stay in the grid**

Replace the return line in `all_permission_keys()`:

```python
    return [m['key'] for m in MODULE_REGISTRY if not m.get('optional') or m.get('per_user')]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_module_enablement.py -p no:cov -v`
Expected: PASS. Then run the wider gate — `venv/Scripts/python.exe -m pytest -m "sales_orders or vendors or customers" -p no:cov -q` — expected PASS (the SO CRUD suite sets `module_enabled:sales_orders='1'` via its autouse fixture, so it is unaffected by the new default-off).

- [ ] **Step 6: Commit**

```bash
git add app/users/module_access.py tests/integration/test_module_enablement.py
git commit -m "feat(sales-orders): gate the module on Products; keep it per-user grantable"
```

---

### Task 2: Drop the `SalesOrderItem.description` column

Remove the column, its serializer key, and the parser field, plus the batch migration; update every test that constructs a line with `description=`.

**Files:**
- Modify: `app/sales_orders/models.py:71` (drop column), `:103` (drop `to_dict` key)
- Modify: `app/sales_orders/views.py:55` (drop `description=` in `_parse_and_attach_so_lines`)
- Create: `migrations/versions/<generated>_drop_so_item_description.py`
- Test: `tests/unit/test_sales_order_model.py`, `tests/unit/test_so_line_parser.py`, `tests/integration/test_sales_orders_crud.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `SalesOrderItem` with no `description` attribute; `to_dict()` with no `'description'` key; `_parse_and_attach_so_lines` no longer reads `description`.

- [ ] **Step 1: Update the unit tests first (they encode the new shape) and add the absence assertion**

In `tests/unit/test_sales_order_model.py`, remove every `description=...` kwarg from the `SalesOrderItem(...)` constructors (lines 11, 20, 27, 47, 48). For example line 11 becomes:

```python
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'),
                        unit_price=Decimal('112.00'), vat_rate=Decimal('12.00'))
```

Apply the same deletion to the other four constructors (drop only the `description='...',` token).
Then extend `test_item_to_dict_has_p56_keys_no_account` with:

```python
    assert 'description' not in d
```

In `tests/unit/test_so_line_parser.py`, delete the `'description': 'Widget',` line from the payload (line 13).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_sales_order_model.py tests/unit/test_so_line_parser.py -p no:cov -v`
Expected: FAIL — `test_item_to_dict_has_p56_keys_no_account` fails on `assert 'description' not in d` (the key is still emitted). The constructor edits alone still pass because `description` is nullable-in-Python until the column is dropped, so this assertion is what drives the change.

- [ ] **Step 3: Drop the column from the model and the serializer**

In `app/sales_orders/models.py`, delete line 71:

```python
    description = db.Column(db.String(500), nullable=False)
```

In `to_dict()` (line 103), remove `'description': self.description,` so the line reads:

```python
            'id': self.id, 'line_number': self.line_number,
```

- [ ] **Step 4: Drop `description` from the line parser**

In `app/sales_orders/views.py`, in `_parse_and_attach_so_lines`, delete the line:

```python
            description=d.get('description', ''),
```

- [ ] **Step 5: Run the unit tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_sales_order_model.py tests/unit/test_so_line_parser.py -p no:cov -v`
Expected: PASS.

- [ ] **Step 6: Update the CRUD integration tests to product-based lines**

In `tests/integration/test_sales_orders_crud.py`, add a product helper next to `_customer`:

```python
def _product(db_session):
    from app.units_of_measure.models import UnitOfMeasure
    from app.products.models import Product
    uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db_session.add(uom); db_session.commit()
    p = Product(code='WIDGET', name='Widget', default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('100.00'), is_active=True)
    db_session.add(p); db_session.commit()
    return p
```

Then in the two POST payloads that use `{'description': 'Widget', ...}` (lines ~52 and ~77), replace `'description': 'Widget'` with `'product_id': str(p.id)` and create the product first. For `test_create_sales_order_persists_and_audits`:

```python
    c = _customer(db_session)
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
```

In `test_duplicate_so_number_rejected` (line ~146) the direct `SalesOrderItem(... description='Blue Widget' ...)` construction: delete the `description='Blue Widget',` token.

- [ ] **Step 7: Scaffold and write the batch migration**

Generate an empty migration (correct `revision`/`down_revision` wired automatically):

Run: `venv/Scripts/python.exe -m flask db revision -m "drop sales_order_items.description"`

Replace the generated `upgrade()`/`downgrade()` bodies with:

```python
def upgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.drop_column('description')


def downgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.String(length=500),
                                      nullable=False, server_default=''))
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.alter_column('description', server_default=None)
```

Ensure `import sqlalchemy as sa` is present at the top of the file (Alembic's template includes it).

- [ ] **Step 8: Verify the migration on a COPY of the real DB**

```bash
cp instance/cas.db instance/_x.db
FLASK_ENV=development SQLALCHEMY_DATABASE_URI=sqlite:///_x.db venv/Scripts/python.exe -m flask db upgrade
# probe: the column must be gone, existing rows intact
venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('instance/_x.db'); \
cols=[r[1] for r in c.execute('PRAGMA table_info(sales_order_items)')]; \
print('description' in cols, c.execute('SELECT COUNT(*) FROM sales_order_items').fetchone()[0])"
rm instance/_x.db
```

Expected: prints `False <n>` — `description` gone, row count preserved (no rows dropped).

- [ ] **Step 9: Run the full SO test set to confirm green**

Run: `venv/Scripts/python.exe -m pytest -m sales_orders -p no:cov -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/sales_orders/models.py app/sales_orders/views.py \
        migrations/versions/*drop_so_item_description*.py \
        tests/unit/test_sales_order_model.py tests/unit/test_so_line_parser.py \
        tests/integration/test_sales_orders_crud.py
git commit -m "feat(sales-orders): drop the line description column (product identifies the line)"
```

---

### Task 3: Product-required server-side guard

Reject any non-empty SO line that has no product. Raise a `ValueError` from the parser and flash it verbatim in create + edit.

**Files:**
- Modify: `app/sales_orders/views.py` (`_parse_and_attach_so_lines` and the `create`/`edit` try blocks)
- Test: `tests/integration/test_sales_orders_crud.py`

**Interfaces:**
- Consumes: `_parse_and_attach_so_lines(so, lines_json)` from Task 2.
- Produces: the parser raises `ValueError(f'Line {n}: select a product.')` when a line has an amount/qty but no `product_id`; `create`/`edit` catch `ValueError` and re-render with the flashed message.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_sales_orders_crud.py`:

```python
def test_line_without_product_is_rejected(client, db_session, admin_user, main_branch):
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    # a real line (amount > 0) but NO product_id -> must be rejected
    lines = json.dumps([{'product_id': None, 'quantity': '1', 'unit_price': '50.00',
                         'vat_category': None, 'vat_rate': '0'}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0100', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'select a product' in resp.data
    assert SalesOrder.query.filter_by(so_number='SO-2026-06-0100').first() is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_sales_orders_crud.py::test_line_without_product_is_rejected" -p no:cov -v`
Expected: FAIL — no guard exists, so the SO persists (or errors generically) and `select a product` is absent.

- [ ] **Step 3: Add the guard in the parser**

In `app/sales_orders/views.py`, replace the body of the `for` loop in `_parse_and_attach_so_lines` with the version below. A line "counts" (must have a product) when it carries an amount or quantity/price; a fully blank trailing line is skipped; kept lines are renumbered sequentially:

```python
    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for idx, d in enumerate(items, start=1):
        vat_rate = _dec(d.get('vat_rate')) or Decimal('0.00')
        product_id = _int(d.get('product_id'))
        amount = Decimal(str(d.get('amount', '0') or '0'))
        qty = _dec(d.get('quantity'))
        price = _dec(d.get('unit_price'))
        is_empty = (product_id is None and (amount is None or amount == 0)
                    and qty is None and price is None)
        if is_empty:
            continue  # skip a blank trailing line
        if product_id is None:
            raise ValueError(f'Line {idx}: select a product.')
        kept += 1
        li = SalesOrderItem(
            line_number=kept,
            quantity=qty,
            unit_price=price,
            uom_text=(d.get('uom_text') or None),
            unit_of_measure_id=_int(d.get('uom_id')),
            product_id=product_id,
            amount=amount,
            vat_category=d.get('vat_category') or None,
            vat_rate=vat_rate,
        )
        li.calculate_amounts()
        so.line_items.append(li)
```

Note: this supersedes the `description=`-removal edit from Task 2 Step 4 (same function) — the whole loop body is now the code above, with no `description` field.

- [ ] **Step 4: Catch `ValueError` in `create` and `edit`**

In `create()` (and the mirror in `edit()`), add a `ValueError` handler BEFORE the broad `except Exception`:

```python
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('sales_orders/form.html', form=form, so=None,
                                   line_items=[], **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating sales order', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_orders.create')
            flash('An error occurred while entering the Sales Order. Please try again.', 'error')
```

For `edit()`, use `so=so` and the edit context in the re-render, matching the existing edit render calls.

- [ ] **Step 5: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_sales_orders_crud.py::test_line_without_product_is_rejected" -p no:cov -v`
Expected: PASS.

- [ ] **Step 6: Run the full SO suite**

Run: `venv/Scripts/python.exe -m pytest -m sales_orders -p no:cov -q`
Expected: PASS (existing create tests now send `product_id`, so they pass the guard).

- [ ] **Step 7: Commit**

```bash
git add app/sales_orders/views.py tests/integration/test_sales_orders_crud.py
git commit -m "feat(sales-orders): reject a line with no product (server-side guard)"
```

---

### Task 4: Product-first SO templates; delete orphan `view.html`

Remove the Description column from the form/detail/print, make Product always-present and required in the form, and delete the unused `view.html`.

**Files:**
- Modify: `app/sales_orders/templates/sales_orders/form.html` (header row ~85-90; line render ~304-312; default line ~298; `onProductPick` ~418-422; `validateForm` ~481-483; submit serialize ~496)
- Modify: `app/sales_orders/templates/sales_orders/detail.html` (line ~199 header, ~212 cell)
- Modify: `app/sales_orders/templates/sales_orders/print.html` (line ~141 cell + its header)
- Delete: `app/sales_orders/templates/sales_orders/view.html`
- Modify: `app/templates/base.html` (bump the SO-form/detail asset `?v=` only if a shared asset changed — templates are not cache-busted, so no bump needed)
- Test: `tests/integration/test_sales_orders_crud.py`

**Interfaces:**
- Consumes: the required-product guard (Task 3) and the dropped column (Task 2).
- Produces: a form whose line row has a required Product select and no Description input; detail/print with no Description column.

- [ ] **Step 1: Write the failing test (rendered form contract)**

Add to `tests/integration/test_sales_orders_crud.py`:

```python
def test_create_form_is_product_first_no_description(client, db_session, admin_user, main_branch):
    _product(db_session)   # ensures products module has data
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:products', '1')
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    db_session.commit(); clear_module_config_cache()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    html = client.get('/sales-orders/create').get_data(as_text=True)
    assert 'onProductPick' in html          # product picker is present
    assert 'desc-${id}' not in html         # the description input template is gone
    assert "'description'" not in html and 'item.description' not in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_sales_orders_crud.py::test_create_form_is_product_first_no_description" -p no:cov -v`
Expected: FAIL — `desc-${id}` and `item.description` are still in the form JS.

- [ ] **Step 3: Edit `form.html` — header row**

Remove the Description `<th>` (line 85) and un-gate the Product `<th>` so it always renders. The header block becomes:

```html
                            <th style="width: 1%; white-space: nowrap; color: var(--text-2);">#</th>
                            <th style="width: 22%;">Product</th>
                            <th style="width: 6%; text-align: right;">Qty</th>
                            <th style="width: 7%;">UOM</th>
                            <th style="width: 10%; text-align: right;">Unit Price</th>
                            <th style="width: 12%; text-align: right;">Amount (VAT-incl.)</th>
                            <th style="width: 14%;">VAT Category</th>
                            <th style="width: 5%;"></th>
```

(If the Product `<th>` was previously wrapped in `{% if module_enabled('products') %}`, drop that wrapper so it is unconditional.)

- [ ] **Step 4: Edit `form.html` — line render, default line, product-pick, validation, serialize**

In `addLineItem`, remove `description: ''` from the default item (line 298):

```javascript
        : { id, product_id: null, quantity: null, uom_id: null, uom_text: null,
            unit_price: null, amount: 0.00, vat_category: '' };
```

Remove the Description `<td>` (lines 306-307) entirely, and make the Product `<td>` unconditional and required (drop the `${productMasterOn ? ...: ''}` wrapper, keep the select, add a required marker class):

```javascript
        <td><select class="form-control" required onchange="onProductPick(${id}, this.value)">
              <option value="">— select product —</option>
              ${products.map(p => `<option value="${p.id}" ${item.product_id == p.id ? 'selected' : ''}>${escHtml(p.code)} — ${escHtml(p.name)}</option>`).join('')}
            </select></td>
```

In `onProductPick`, remove the description autofill block (lines 418-422):

```javascript
    if (!p) return;
    if (p.default_uom_id != null) {
```

In `validateForm`, replace the description requirement (lines 481-483) with a product requirement on every line:

```javascript
        if (!item.amount || item.amount <= 0) { block(`Line ${n}: enter an amount greater than zero.`); return; }
        if (!item.product_id) { block(`Line ${n}: select a product.`); return; }
```

In the submit serializer, remove `description: item.description,` (line 496).

- [ ] **Step 5: Edit `detail.html` and `print.html` — drop the Description column**

In `detail.html`, remove the Description `<th>` (line 199) and the Description `<td>` (line 212 `<td>{{ item.description or '—' }}</td>`).
In `print.html`, remove the Description header cell and the Description `<td>` (line 141).

- [ ] **Step 6: Delete the orphan `view.html`**

```bash
git rm app/sales_orders/templates/sales_orders/view.html
```

(Confirmed no route renders it and it is not `{% include %}`d.)

- [ ] **Step 7: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_sales_orders_crud.py::test_create_form_is_product_first_no_description" -p no:cov -v`
Expected: PASS.

- [ ] **Step 8: Run the full SO suite + the earlier display regression test**

Run: `venv/Scripts/python.exe -m pytest -m sales_orders -p no:cov -q`
Expected: PASS — including `test_detail_view_no_entity_leak_and_no_currency_glyph` (detail still clean).

- [ ] **Step 9: Commit**

```bash
git add app/sales_orders/templates/sales_orders/form.html \
        app/sales_orders/templates/sales_orders/detail.html \
        app/sales_orders/templates/sales_orders/print.html \
        tests/integration/test_sales_orders_crud.py
git rm app/sales_orders/templates/sales_orders/view.html
git commit -m "feat(sales-orders): product-first line UI, drop Description column, remove orphan view.html"
```

---

## Post-implementation

- Browser-verify via MCP: with Products + UoM + SO enabled, create an SO — the line row shows a required Product picker (no Description), product-pick autofills UoM + unit price, and the detail/print show the product with no Description column.
- The two demo drafts (`SO-2026-07-0001/0002`) were created pre-change with no product; they remain readable (product cell `—`) but cannot be edited-and-saved without adding a product. Recreate them if a clean demo is wanted.
- `/guard` before pushing (the SO templates + `module_access.py` are blast-radius files).
