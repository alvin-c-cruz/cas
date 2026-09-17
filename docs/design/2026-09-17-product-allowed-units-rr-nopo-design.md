# Per-product allowed units for no-PO receiving lines

**Date:** 2026-09-17
**Status:** Approved design, pending implementation plan
**Scope:** Constrain the unit of measure a receiver may choose on a *no-PO*
("Add Item Without PO") receiving-report line, so it is limited to a per-product
allowed set curated by an admin — instead of accepting any active unit.

---

## Problem

On the Receiving Reports create/edit form, an "Add Item Without PO" (direct)
line lets the receiver pick **any active unit of measure** for the chosen
product. The `directUom` picker is populated from the full `UnitOfMeasure` list,
and the server (`app/receiving_reports/views.py::_parse_rr_lines`) validates only
that the submitted `unit_of_measure_id` **exists and is active** — never that it
is appropriate for the product. Because the data model has **no unit-conversion
factors**, a line received in a unit other than the product's default cannot be
converted or valued consistently against that product. A receiver (or a raw
POST) can therefore attach, say, `pcs` to a product whose default is `kg`, and
the save succeeds.

There is today no concept of "units this product may be received in" beyond the
single, nullable `Product.default_unit_of_measure_id`.

## Goals

- Let an admin curate, per product, the set of units acceptable for **no-PO
  receiving-report lines**.
- Enforce that set on no-PO RR lines, both in the UI (filter the picker) and on
  the server (authoritative — a raw POST bypasses the picker).
- Ship with **zero risk to existing data and flows**: a product with no curated
  set behaves exactly as today.

## Non-goals

- No enforcement anywhere other than no-PO RR lines. PO-backed RR lines, and
  every other document that selects a product's unit (PO, PR, quotations, SI,
  SO, memos, AP/CDV/CRV), are untouched. The allowed-units relationship is
  modelled as a reusable product attribute, but only RR no-PO enforcement is in
  scope here.
- **No unit-conversion system.** This feature curates *which* units are
  acceptable; it does not convert between them. (The mixed-unit valuation
  concern is mitigated, not solved, and solving it is out of scope.)
- No backfill of existing products (opt-in semantics make backfill unnecessary).

## Key semantics (decisions)

1. **Opt-in.** A product with an **empty** allowed set is *unconstrained* — any
   active unit is accepted, exactly as today. The constraint applies only to
   products where an admin has explicitly curated a set. No migration/backfill
   of existing rows is required.
2. **Default always allowed.** Even when a set is curated, a line whose unit is
   left blank (→ the product's default) is always accepted, and the product's
   `default_unit_of_measure_id` is treated as an implicit member of the set.
   A product can never be locked out of its own default.
3. **Two layers of enforcement.** The RR picker filters to the allowed set for
   UX; the server re-enforces because a raw POST bypasses the picker (mirrors the
   existing product-id / open-qty validation philosophy in `_parse_rr_lines`).

---

## 1. Data model

New association table **`product_allowed_units`** (many-to-many between
`products` and `units_of_measure`):

| column                | type    | notes                                             |
|-----------------------|---------|---------------------------------------------------|
| `id`                  | Integer | PK                                                |
| `product_id`          | Integer | FK → `products.id`, NOT NULL                       |
| `unit_of_measure_id`  | Integer | FK → `units_of_measure.id`, NOT NULL              |

- Unique constraint on `(product_id, unit_of_measure_id)`.
- **No `branch_id`** — products are company-wide master data (the `products`
  table has no `branch_id`).

**Migration** `migrations/versions/prodau_0001_product_allowed_units.py`:

- `down_revision = 'apamd_0001'` (current head).
- Uses `op.create_table(...)` (no batch wrapper — batch mode is only for
  altering an existing table).
- **Names every constraint explicitly** inside `create_table`
  (`fk_product_allowed_units_product_id`,
  `fk_product_allowed_units_unit_of_measure_id`,
  `uq_product_allowed_units_product_unit`), per the CAS migration rules — an
  unnamed FK cannot be reproduced by a later batch rebuild.
- Verified against a **copy of a real database**, not a `create_all()` test DB.

**`Product` model** (`app/products/models.py`) gains:

- `allowed_units` — relationship to `UnitOfMeasure` via the association table.
- `allowed_unit_ids()` → `set[int]` of the associated unit ids. **Empty set means
  unconstrained.**
- `unit_allowed(uom_id)` → `bool`. Returns `True` when:
  - the allowed set is empty (unconstrained), **or**
  - `uom_id` is in the allowed set, **or**
  - `uom_id == self.default_unit_of_measure_id` (default always allowed).

  A falsy `uom_id` (blank → falls back to default) is always allowed.

## 2. Admin UI (product create / edit)

- `ProductForm` (`app/products/forms.py`) gains
  `allowed_unit_ids = SelectMultipleField('Allowed Units (no-PO receiving)',
  coerce=int, validators=[Optional()])`, choices populated with **active** units
  (same source the existing `default_unit_of_measure_id` select uses).
- Template (`app/products/templates/products/form.html`): a multi-select listbox
  rendered like `user.branch_ids`
  (`{{ form.allowed_unit_ids(multiple=true, size=5, ...) }}`), with a hint:
  *"Leave empty to allow any active unit. Selecting units limits no-PO receiving
  to those units (the default unit is always allowed)."*
- `products.create` / `products.edit` (`app/products/views.py`) persist the set:
  on create, add the selected associations; on edit, replace them (clear + re-add
  the current selection). Existing pre-populate on the edit GET reflects the saved
  set.
- **Permission unchanged** — editing a product is already accountant-or-above;
  the allowed-units field rides on the same route/guard.
- **Audit:** the product update audit uses `get_changes` on scalar columns, which
  will not see an association change. The create/edit views will explicitly
  include the allowed-unit set (before/after, as sorted unit ids or codes) in the
  audited values so the change is recorded, not silently dropped. (Consistent with
  the audit caveat in CLAUDE.md: verify the audit log in CRUD tests via the real
  HTTP route.)

## 3. Receiving-report enforcement

- `_direct_products_payload()` (`app/receiving_reports/views.py`, ~line 329) adds
  `allowed_unit_ids: [int, ...]` to each product dict (empty list when
  unconstrained). This reaches the form as `DIRECT_PRODUCTS`.
- **UI filter** (`app/receiving_reports/templates/receiving_reports/form.html`,
  the no-PO picker block): when a product is selected, rebuild the `directUom`
  options to the product's allowed set **plus its default**; when the set is
  empty, show all active units (today's behavior). Rebuilt on product change,
  through the Choices instance when the select is enhanced (`setChoiceByValue` /
  repopulate, not a bare `.value` assignment — the wrapped widget does not repaint
  from a raw DOM write).
- **Server guard** in `_parse_rr_lines` (the direct-line branch, after the
  existing product and unit existence/active checks): if the product has a
  non-empty allowed set and the submitted `uom_id` is neither in the set nor the
  product's default →
  `raise ValueError('Line {position}: {unit code} is not an allowed unit for
  {product name}. Choose one of: {allowed codes}.')`. A blank `uom_id`
  (→ default) always passes. This is the authoritative check.

## 4. Edge cases

- **Empty set → unconstrained** (opt-in). No behavior change for any product that
  isn't curated.
- **Default always allowed**, even if not explicitly listed in the set.
- **Inactive unit:** already rejected by the existing "unit must exist and be
  active" check in `_parse_rr_lines`; the picker only offers active units, and an
  inactive unit sitting in a product's curated set is simply never offered and
  fails the active check if forced via raw POST.
- **Hard-deleting a unit that some product allows:** the FK prevents it. Units are
  normally deactivated (`is_active=False`), not hard-deleted, so no cascade is
  needed; blocking a hard delete is the safe outcome.
- **Raw POST bypass:** covered by the server guard.

## 5. Testing

- **Unit** (`tests/unit/`): `Product.allowed_unit_ids()` and `unit_allowed()` —
  empty set allows all; a curated set constrains; the default is always allowed
  (in and out of the set); blank uom always allowed.
- **Product form** (`tests/integration/test_products_crud.py` or a new file):
  saving a product with a curated set persists the association; editing to a
  different set replaces it; clearing it removes all rows; the audit log records
  the allowed-units change (exercised through the real HTTP route).
- **RR server** (`tests/integration/`): via the create route —
  - product with **no** set → any active unit accepted (unchanged);
  - product **with** set → an in-set unit is accepted;
  - out-of-set unit → line rejected with the specific message, nothing saved;
  - blank unit → accepted (uses default) even when the default is not explicitly
    in the set;
  - **raw POST** with an out-of-set unit → rejected (proves the picker filter is
    not the enforcement).
- **Payload** (`tests/integration/test_rr_form_render.py` or the RR views tests):
  `_direct_products_payload()` output includes `allowed_unit_ids`.
- **Migration:** apply `prodau_0001` on a copy of a real DB; confirm the table,
  named constraints, and that `flask db upgrade`/`downgrade` round-trip.

## Files touched

- `migrations/versions/prodau_0001_product_allowed_units.py` (new)
- `app/products/models.py` (relationship + helpers)
- `app/products/forms.py` (`allowed_unit_ids` field)
- `app/products/templates/products/form.html` (multi-select + hint)
- `app/products/views.py` (persist set on create/edit; audit before/after)
- `app/receiving_reports/views.py` (`_direct_products_payload` + `_parse_rr_lines`
  guard)
- `app/receiving_reports/templates/receiving_reports/form.html` (picker filter)
- Tests as listed in §5.

## Rollout

Additive and opt-in: shipping the migration + code changes nothing for any
existing product until an admin curates a set. No data migration, no backfill,
no reload-order constraints beyond the usual deploy (migration then reload).
