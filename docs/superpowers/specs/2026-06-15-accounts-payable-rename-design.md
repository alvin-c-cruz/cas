# Rename: `purchase_bills` → `accounts_payable`

**Date:** 2026-06-15
**Scope:** Full depth — Python code, templates, CSS, DB tables/columns, tests
**Approach:** Module scaffold first, then parallel fan-out, migration + tests last

---

## 1. Goal

Replace every trace of the "bill" naming convention with "accounts_payable" (or its abbreviated `ap_` form for fields and short identifiers). The AP Voucher feature currently uses `PurchaseBill`, `bill_number`, `bill_date`, `/purchase-bills/` routes, and related names throughout. After this rename the module, its models, DB tables, columns, routes, templates, CSS, and tests all speak the same domain language.

---

## 2. Naming Map

### Module & Classes

| Old | New |
|---|---|
| `app/purchase_bills/` | `app/accounts_payable/` |
| `PurchaseBill` | `AccountsPayable` |
| `PurchaseBillItem` | `AccountsPayableItem` |
| `PurchaseBillAttachment` | `AccountsPayableAttachment` |
| `PurchaseBillForm` | `AccountsPayableForm` |
| `purchase_bills_bp` | `accounts_payable_bp` |
| blueprint name `'purchase_bills'` | `'accounts_payable'` |
| `compute_bills_summary()` | `compute_ap_summary()` |

### Database Tables

| Old | New |
|---|---|
| `purchase_bills` | `accounts_payable` |
| `purchase_bill_items` | `accounts_payable_items` |
| `purchase_bill_attachments` | `accounts_payable_attachments` |

### Database Columns

| Table | Old column | New column |
|---|---|---|
| `purchase_bills` → `accounts_payable` | `bill_number` | `ap_number` |
| `purchase_bills` → `accounts_payable` | `bill_date` | `ap_date` |
| `purchase_bill_items` → `accounts_payable_items` | `bill_id` | `ap_id` |
| `purchase_bill_attachments` → `accounts_payable_attachments` | `bill_id` | `ap_id` |
| `cdv_ap_lines` (unchanged table name) | `bill_id` | `ap_id` |
| `cdv_ap_lines` (unchanged table name) | `bill_number` | `ap_number` |

### Routes & URLs

| Old | New |
|---|---|
| `/purchase-bills` | `/accounts-payable` |
| `/purchase-bills/create` | `/accounts-payable/create` |
| `/purchase-bills/<id>` | `/accounts-payable/<id>` |
| `/purchase-bills/<id>/edit` | `/accounts-payable/<id>/edit` |
| `/purchase-bills/<id>/post` | `/accounts-payable/<id>/post` |
| `/purchase-bills/<id>/cancel` | `/accounts-payable/<id>/cancel` |
| `/purchase-bills/<id>/void` | `/accounts-payable/<id>/void` |
| `/purchase-bills/<id>/print` | `/accounts-payable/<id>/print` |
| `/purchase-bills/export/excel` | `/accounts-payable/export/excel` |
| `/purchase-bills/export/csv` | `/accounts-payable/export/csv` |
| `/purchase-bills/print` | `/accounts-payable/print` |
| `/purchase-bills/<id>/attachments/upload` | `/accounts-payable/<id>/attachments/upload` |
| `/purchase-bills/attachments/<id>/download` | `/accounts-payable/attachments/<id>/download` |
| `/purchase-bills/attachments/<id>/preview` | `/accounts-payable/attachments/<id>/preview` |
| `/purchase-bills/attachments/<id>/delete` | `/accounts-payable/attachments/<id>/delete` |

### View Functions

| Old | New |
|---|---|
| `list_bills()` | `list_ap()` |
| `print_bill()` | `print_ap()` |
| `generate_bill_number()` | `generate_ap_number()` |
| `_get_bill_or_404()` | `_get_ap_or_404()` |
| `_bill_upload_dir()` | `_ap_upload_dir()` |
| `VALID_BILL_STATUSES` | `VALID_AP_STATUSES` |
| `export_excel()` | unchanged |
| `export_csv_route()` | unchanged |
| `print_list()` | unchanged |
| `create()` | unchanged |
| `view()` | unchanged |
| `edit()` | unchanged |
| `post()` | unchanged |
| `cancel()` | unchanged |
| `void()` | unchanged |
| `upload_attachment()` | unchanged |
| `download_attachment()` | unchanged |
| `preview_attachment()` | unchanged |
| `delete_attachment()` | unchanged |

### Templates & Static

| Old | New |
|---|---|
| `app/purchase_bills/templates/purchase_bills/*.html` | `app/accounts_payable/templates/accounts_payable/*.html` |
| `app/static/purchase_bills_form.css` | `app/static/accounts_payable_form.css` |
| Template variable `{{ bill }}` | `{{ ap }}` |
| `{{ bill.bill_number }}` | `{{ ap.ap_number }}` |
| `{{ bill.bill_date }}` | `{{ ap.ap_date }}` |
| `url_for('purchase_bills.*')` | `url_for('accounts_payable.*')` |
| CSS `.bill-summary-panel` | `.ap-summary-panel` |
| CSS `.page-purchase-bill` | `.page-accounts-payable` |

### Cross-Module References

| File | Change |
|---|---|
| `app/__init__.py` | Import path + blueprint variable name |
| `app/cash_disbursements/models.py` | `CDVApLine.bill_id` → `ap_id`, `.bill` → `.accounts_payable`, `.bill_number` → `.ap_number` |
| `app/journals/views.py` | Import `AccountsPayable`, `bill_map` → `ap_map`, `_entry_identity` args |
| `app/journals/ap_journal_data.py` | Any `bill_number` / `PurchaseBill` references |
| All templates with `url_for('purchase_bills.*')` | Updated to `accounts_payable.*` |

### Tests

| Old | New |
|---|---|
| `tests/integration/test_purchase_bill_dates.py` | `test_accounts_payable_dates.py` |
| `tests/integration/test_purchase_bill_detail.py` | `test_accounts_payable_detail.py` |
| `tests/integration/test_purchase_bill_je.py` | `test_accounts_payable_je.py` |
| `tests/integration/test_purchase_bill_lifecycle.py` | `test_accounts_payable_lifecycle.py` |
| `tests/integration/test_purchase_bill_override.py` | `test_accounts_payable_override.py` |
| `tests/integration/test_purchase_bill_vat_buckets.py` | `test_accounts_payable_vat_buckets.py` |
| `tests/integration/test_purchase_bill_views.py` | `test_accounts_payable_views.py` |
| Internal: `PurchaseBill(...)` → `AccountsPayable(...)`, `bill_number` → `ap_number`, etc. |

### Upload Directory

| Old | New |
|---|---|
| `instance/uploads/purchase_bills/` | `instance/uploads/accounts_payable/` |

Note: The code change updates the path constant. On PythonAnywhere, after `flask db upgrade`, manually rename the upload folder to preserve existing attachments.

---

## 3. Migration

One new Alembic migration using `op.batch_alter_table` (required for SQLite — native `ALTER COLUMN` is not supported):

```python
def upgrade():
    # 1. purchase_bills → accounts_payable; rename bill_number, bill_date
    with op.batch_alter_table('purchase_bills',
                               new_table_name='accounts_payable') as batch_op:
        batch_op.alter_column('bill_number', new_column_name='ap_number')
        batch_op.alter_column('bill_date', new_column_name='ap_date')

    # 2. purchase_bill_items → accounts_payable_items; rename bill_id → ap_id
    with op.batch_alter_table('purchase_bill_items',
                               new_table_name='accounts_payable_items') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')

    # 3. purchase_bill_attachments → accounts_payable_attachments; rename bill_id
    with op.batch_alter_table('purchase_bill_attachments',
                               new_table_name='accounts_payable_attachments') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')

    # 4. cdv_ap_lines — rename bill_id, bill_number (table stays cdv_ap_lines)
    with op.batch_alter_table('cdv_ap_lines') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')
        batch_op.alter_column('bill_number', new_column_name='ap_number')


def downgrade():
    with op.batch_alter_table('cdv_ap_lines') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')
        batch_op.alter_column('ap_number', new_column_name='bill_number')

    with op.batch_alter_table('accounts_payable_attachments',
                               new_table_name='purchase_bill_attachments') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')

    with op.batch_alter_table('accounts_payable_items',
                               new_table_name='purchase_bill_items') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')

    with op.batch_alter_table('accounts_payable',
                               new_table_name='purchase_bills') as batch_op:
        batch_op.alter_column('ap_number', new_column_name='bill_number')
        batch_op.alter_column('ap_date', new_column_name='bill_date')
```

**Existing migration files** (10 historical migrations) are left untouched — Alembic uses them only for the revision chain, not re-execution.

---

## 4. Execution Strategy

Six tasks executed via `subagent-driven-development`. Task 1 is sequential; Tasks 2–5 run in parallel after Task 1 completes; Task 6 is sequential last.

### Task 1 — Module scaffold (sequential, runs first)
- Delete `app/purchase_bills/` directory
- Create `app/accounts_payable/` with empty `__init__.py`
- Create stub files for `models.py`, `forms.py`, `views.py`, `utils.py` (empty, to be filled by Task 2/3)
- Create `app/accounts_payable/templates/accounts_payable/` directory

### Task 2 — Python core (parallel)
Rewrite `models.py`, `forms.py`, `utils.py`:
- `AccountsPayable`, `AccountsPayableItem`, `AccountsPayableAttachment` with new `__tablename__` values and column names
- `AccountsPayableForm` with `ap_number`, `ap_date` fields
- `compute_ap_summary()` in `utils.py`
- Update `app/__init__.py`: import `accounts_payable_bp`, register it

### Task 3 — Views (parallel)
Rewrite `views.py`:
- All route URLs changed to `/accounts-payable/…`
- Function renames: `list_ap`, `print_ap`, `generate_ap_number`, `_get_ap_or_404`, `_ap_upload_dir`, `VALID_AP_STATUSES`
- All internal variable names: `bill` → `ap`, `bills` → `ap_list`
- Upload path: `instance/uploads/accounts_payable/`
- Template `render_template` calls updated to `accounts_payable/*.html`
- All `url_for('purchase_bills.*')` → `url_for('accounts_payable.*')`

### Task 4 — Templates + CSS (parallel)
- Copy and rewrite all 5 HTML templates into `accounts_payable/templates/accounts_payable/`
- `{{ bill }}` → `{{ ap }}` throughout
- `{{ bill.bill_number }}` → `{{ ap.ap_number }}`, `{{ bill.bill_date }}` → `{{ ap.ap_date }}`
- All `url_for('purchase_bills.*')` → `url_for('accounts_payable.*')`
- Rename `purchase_bills_form.css` → `accounts_payable_form.css`
- `.bill-summary-panel` → `.ap-summary-panel`
- `.page-purchase-bill` → `.page-accounts-payable`
- Update `<link>` tag in form template to new CSS filename

### Task 5 — Cross-module references (parallel)
- `app/cash_disbursements/models.py`: `CDVApLine.bill_id` → `ap_id`, `.bill` relationship → `.accounts_payable`, `.bill_number` → `.ap_number`; update FK string `'purchase_bills.id'` → `'accounts_payable.id'`; update model reference `'PurchaseBill'` → `'AccountsPayable'`
- `app/journals/views.py`: import `AccountsPayable`, `bill_map` → `ap_map`, update query field names (`bill_number` → `ap_number`, `bill_date` → `ap_date`)
- `app/journals/ap_journal_data.py`: update any `bill_number` / `PurchaseBill` references
- Any other template referencing `url_for('purchase_bills.*')` (e.g., `sales_invoices/list.html` sidebar links, base navigation)

### Task 6 — Migration + tests (sequential, runs last)
- Generate migration: `flask db migrate -m "rename purchase_bills to accounts_payable"`
- Review and correct generated migration to match the spec exactly (add `new_table_name`, verify column renames)
- Run: `flask db upgrade`
- Rename test files (7 files) and rewrite internals: `PurchaseBill(` → `AccountsPayable(`, `bill_number=` → `ap_number=`, `bill_date=` → `ap_date=`, import paths
- Run full test suite: `pytest`; fix any failures

---

## 5. Out of Scope

- The CDV module itself (`app/cash_disbursements/`) is not renamed — only the two fields on `CDVApLine` that reference the AP table
- Historical migration files are not modified
- `url_for` calls in the base navigation / sidebar template referencing `purchase_bills.*` are in scope for Task 5
- PythonAnywhere upload folder rename is a manual step post-deploy (documented in migration comment)
