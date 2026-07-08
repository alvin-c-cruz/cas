# Sales Order — Product-Based Lines (drop free-text Description) — Design

**Date:** 2026-07-08 · **Roadmap:** R-01 Sales (Order-to-Cash) · **Status:** proposed

## Goal

Redefine the Sales Order as a **product-based operational document**. Each SO line **is a
Product** (required); the product identifies the line and autofills UoM + unit price. The
free-text per-line **Description is removed entirely**. The Sales Order module becomes an
**optional, configuration-gated module that requires (depends on) the Products module** (and
transitively Units of Measure).

## Rationale

- SO is **operational-only — it posts no journal entry**, so unlike SI/AP/CDV/CRV it has no need
  for a Description as JE particulars. The product name is sufficient line identity. (This is why
  the Product/UoM-activation rule "Description is always present on the four JE documents" does
  **not** bind SO — SO is not one of those four.)
- Ordering is inherently product-centric; a free-text line invites uncatalogued orders and blocks
  clean downstream SI / inventory linkage.
- Gating SO behind Products enforces that an SO-using client maintains a product catalogue.

## Confirmed design decisions

1. **Drop `SalesOrderItem.description`** — hard-drop the column (migration) and remove it from all
   SO UI (form / detail / print) and serialization.
2. **Product required per line** — enforced by a **server-side validation guard** (reject any SO
   line with no `product_id`). No `product_id nullable=False` schema change: the guard is the
   enforcement layer (mirrors the Product/UoM-activation "half-filled line" guard philosophy) and
   it leaves pre-existing draft rows readable. The Product column is **always shown and required**
   in the form; product-pick autofills **UoM + unit price** (SO carries no GL account).
3. **Module gating** — the `sales_orders` registry entry becomes
   `optional: True, depends_on: ['products'], default_enabled: False, per_user: True`. Products is
   already `depends_on ['units_of_measure']`, so enabling SO **transitively requires Products +
   UoM**, enforced by the existing depends-on DAG (`app/users/module_access.py:158`).

## Architecture / components

### Model — `app/sales_orders/models.py`
- Remove `description = db.Column(db.String(500), nullable=False)` from `SalesOrderItem`.
- Remove the `'description'` key from `SalesOrderItem.to_dict()`.
- `product_id` stays `nullable=True` (guard enforces presence at write time).

### Migration (hand-written, batch)
- `Migrate()` runs **without** `render_as_batch`, so hand-write:
  `with op.batch_alter_table('sales_order_items') as batch: batch.drop_column('description')`
  (SQLite batch recreates the table). Downgrade re-adds `description` as
  `sa.String(500)` with `server_default=''` then drops the default (so the historical
  `nullable=False` is restorable without failing on rebuilt rows).
- **Verify on a COPY of a real DB** (`cas.db`) per `migration-verify-on-real-db-copy`: run
  `flask db upgrade`, assert the column is gone and existing SO rows are intact.

### Views — `app/sales_orders/views.py`
- `_parse_and_attach_so_lines`: drop `description=d.get('description', '')`.
- **New guard** (create + edit both route through the parser / a shared validate step): if any
  non-empty line has no `product_id`, flash an error and re-render the form — the SO is **not**
  persisted. Empty trailing lines are skipped as today.

### Templates — `app/sales_orders/templates/sales_orders/`
- `form.html`: remove the Description column (header + `#desc-` input + the JS default-line
  `description` field + its serialization + the "enter a description" client validation). Make the
  **Product** column **always rendered** (no longer gated by `module_enabled('products')`, since SO
  now requires products) and **required**. Keep product-pick autofill of UoM + unit price; remove
  the `item.description = p.name` line (no description field remains).
- `detail.html`: remove the Description `<th>` + `<td>`.
- `print.html`: remove the Description column.
- `list.html`: no per-line description is shown — no change beyond the already-applied display fixes.
- **Delete `view.html`** — orphan template (no route renders it, not `{% include %}`d) that also
  references `item.description`.

### Module registry — `app/users/module_access.py`
- `sales_orders` entry → `optional: True, depends_on: ['products'], default_enabled: False,
  per_user: True`. All permission-grid / sidebar / before_request machinery already reads the
  registry, so it follows automatically.

## Ripple effects / blast radius

`SalesOrderItem.description` is removed app-wide. Enumerated touch-points (from a full grep):
`models.py` (column + `to_dict`), `views.py` (parser), `form.html` (5 spots), `detail.html`,
`print.html`, orphan `view.html`; and tests `test_sales_order_model.py`, `test_so_line_parser.py`,
`test_sales_orders_crud.py`.

- **Existing demo drafts** `SO-2026-07-0001/0002` were created with description + no product. After
  the migration they lose `description`; they also have no product, so they violate the new guard —
  but the guard runs on **write** (create/edit), not read, so they still **display** (product cell
  shows `—`, qty/amount intact). Acceptable for demo data; recreate if desired.
- `calculate_amounts()` (amount = qty × unit_price) is unaffected.
- **SI↔SO linkage** (future) will consume product-based SO lines — beneficial, out of scope here.

## Out of scope

- SI↔SO "create SI from SO" linkage.
- Inventory / stock / COGS (R-03).
- `product_id nullable=False` at the schema level (guard-only for now).
- App-wide currency-symbol strip beyond SO (separate task).

## Testing plan (TDD)

- **Unit:** model constructs without `description`; parser produces product-based lines; the
  no-product guard rejects a line with no `product_id`; the module DAG blocks enabling
  `sales_orders` while `products` is off.
- **Integration:** create/edit persists product lines + audit; detail renders the product and has
  no Description column (and still no `&#8212;` / peso glyph — existing regression test); the create
  form shows a required Product column and **no** Description column.
- **Migration:** `flask db upgrade` on a copy of `cas.db` — assert `description` column gone,
  existing rows intact.
