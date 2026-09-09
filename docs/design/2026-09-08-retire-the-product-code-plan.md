# Retiring the Product Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Product.code` optional and invisible to the user, starting with the purchasing area, without destroying the codes already recorded or the documents already printed.

**Architecture:** Two moves, deliberately separated. The schema move makes the column nullable so a product can exist without a code — reversible, no data lost. The display move stops every user-facing surface rendering it. History is left alone: stored revision snapshots and posted journal entries keep the codes they were written with, because they record what was actually issued.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, SQLite, Alembic (hand-written migrations), Jinja2, vanilla JS, pytest.

**Owner decisions, 2026-09-08:**
- Approach **C** — make it optional first, delete later if it proves unwanted. Not a hard removal.
- The user must **not see it anywhere in the app**.
- Purchasing area **first**.

## Global Constraints

- **`code` keeps its `unique=True` index.** SQLite permits multiple NULLs under a unique index, so new products simply have none while the 555 existing codes stay unique. Do not drop the index — that is the irreversible half.
- **Do not make `name` unique.** The owner asked for optional-and-hidden. Adding a new constraint would smuggle a second, irreversible decision in alongside a reversible one. Live data: 554 distinct names across 555 products, the one collision being test records (`SPIN DRYER` / `ABC123`).
- **Do not rewrite history.** Stored `DocumentRevision` snapshots hold `product_code`, and posted journal entries carry it in their line descriptions. Both record what was actually issued. New ones stop carrying it; existing ones are untouched.
- **Migrations are hand-written** with `op.batch_alter_table`; `Migrate()` has no `render_as_batch`. Verify against a copy of `instance/philgen.db`, never a `create_all()` test database.
- **Never a naive `datetime.now()`** — `ph_now()` is the clock.
- **Absence assertions must be scoped** to an applied attribute or an extracted element; inline `<style>` and JS text leak into rendered responses, so a bare-word probe can never fail. This matters more than usual here: the string `code` appears everywhere, including in `uom.code` and `account.code`, which must keep rendering.
- **Do not touch `Product.customer_code`.** It is the CUSTOMER's own SKU, a different field that stays. Every edit must distinguish `product.code` from `customer_code`, `unit_of_measure.code` and `account.code`.
- Restart the dev server after any `.py` change — `flask_app.py` runs `use_reloader=False`.

---

## Scope

**Phase 1 — this plan.** Schema, the purchasing area, and the products module itself. That is a coherent shippable slice: no new product needs a code, and nothing in purchasing shows one.

**Phase 2 — a later plan, not this one.** Sales (delivery receipts, sales orders, invoices, quotations, memos), inventory and manufacturing (stock adjustments, BOM, work orders, production runs), and reports. Roughly 60 further references. Named here so the boundary is deliberate rather than forgotten.

Counted 2026-09-08: 32 references in the purchasing area, ~96 Python and 44 templates in total.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `migrations/versions/prodcode_0001_product_code_optional.py` | the nullability change | create |
| `app/products/models.py` | the column | modify |
| `app/products/forms.py` | stop requiring it | modify |
| `app/products/views.py` | list sort, audit identity, payloads | modify |
| `app/products/templates/products/*.html` | list and form | modify |
| `app/purchase_orders/models.py` | snapshot + to_dict payloads | modify |
| `app/purchase_requests/{models,allocation}.py` | snapshot + picker payload | modify |
| `app/receiving_reports/{models.py,stock_posting.py}` | payload + JE line text | modify |
| `app/*/templates/**` (purchasing) | pickers, overlays, line tables | modify |
| `tests/integration/test_product_code_retired.py` | the new behaviour | create |

---

## Task 1: Make the column optional

**Files:**
- Create: `migrations/versions/prodcode_0001_product_code_optional.py`
- Modify: `app/products/models.py`
- Test: `tests/integration/test_product_code_retired.py`

**Interfaces:**
- Consumes: nothing. Confirm the current head first.
- Produces: `Product.code` nullable; a product can be created with `code=None`.

- [ ] **Step 1: Confirm the migration head**

Run: `flask db heads`
Note what it prints and use it as `down_revision`. Do not assume — this repository has had several migrations land in quick succession.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_product_code_retired.py`:

```python
"""Product.code becomes optional, then invisible.

Owner, 2026-09-08: clients do not use the product code. Approach C was chosen
deliberately over deleting the column -- make it optional and hide it, so the 555
codes already recorded survive and the decision stays reversible.

The unique index is KEPT. SQLite permits multiple NULLs under a unique index, so
new products simply have no code while existing ones stay unique. Dropping the
index is the irreversible half and is not part of this change.

`name` is NOT made unique. That would be a second, irreversible decision smuggled
in beside a reversible one -- and the master legitimately allows two products to
share a name.
"""
import pytest

from app.products.models import Product

pytestmark = [pytest.mark.integration]


class TestTheColumn:

    def test_code_is_optional(self):
        assert Product.__table__.c.code.nullable is True

    def test_code_keeps_its_unique_index(self):
        """The reversible half of the change. Dropping this would let duplicate
        codes in among the 555 already recorded, which no later step could undo."""
        assert Product.__table__.c.code.unique is True

    def test_name_did_not_become_unique(self):
        """CONTROL. The owner asked for optional-and-hidden; a new NOT NULL or
        UNIQUE constraint elsewhere is not part of that."""
        assert not Product.__table__.c.name.unique

    def test_customer_code_is_untouched(self):
        """A different field -- the CUSTOMER's own SKU. Easy to catch in a sweep
        for the word 'code' and delete by accident."""
        assert 'customer_code' in {c.key for c in Product.__table__.columns}


class TestAProductCanExistWithoutACode:

    def test_it_saves(self, db_session):
        p = Product(code=None, name='CODELESS ITEM', is_active=True)
        db_session.add(p)
        db_session.commit()
        assert p.id is not None
        assert p.code is None

    def test_two_of_them_can_coexist(self, db_session):
        """THE reason the unique index is safe to keep: NULLs do not collide."""
        db_session.add(Product(code=None, name='CODELESS ONE', is_active=True))
        db_session.add(Product(code=None, name='CODELESS TWO', is_active=True))
        db_session.commit()
        assert Product.query.filter(Product.code.is_(None)).count() == 2

    def test_a_duplicate_REAL_code_is_still_refused(self, db_session):
        """CONTROL for the two tests above: making NULLs legal must not make
        duplicate codes legal. The 555 existing codes stay unique."""
        from sqlalchemy.exc import IntegrityError
        db_session.add(Product(code='RM-DUP-1', name='FIRST', is_active=True))
        db_session.commit()
        db_session.add(Product(code='RM-DUP-1', name='SECOND', is_active=True))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_product_code_retired.py -q --no-cov`
Expected: FAIL — `assert False is True` on nullability, and an IntegrityError creating a codeless product.

- [ ] **Step 4: Write the migration**

Create `migrations/versions/prodcode_0001_product_code_optional.py`, using the head from Step 1 as `down_revision`:

```python
"""products.code becomes optional

Owner, 2026-09-08: clients do not use the product code, and it is being retired
from every screen. This is the reversible half -- the column and its 555 values
stay, and the unique index stays with them; only the NOT NULL goes.

The unique index is deliberately RETAINED. SQLite permits multiple NULLs under a
unique index, so products created from here on simply have no code while every
existing code stays unique. Dropping the index would let duplicates in among the
recorded codes, and no later step could sort that out.

Revision ID: prodcode_0001
Revises: <HEAD FROM STEP 1>
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa


revision = 'prodcode_0001'
down_revision = '<HEAD FROM STEP 1>'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.alter_column('code', existing_type=sa.String(length=50),
                              nullable=True)


def downgrade():
    """Refuses while any product has no code.

    Restoring NOT NULL with codeless rows present would fail mid-rebuild, or --
    worse, if someone 'helpfully' backfilled -- invent codes that were never
    assigned. Better to stop and let the operator decide what those products
    should be called.
    """
    conn = op.get_bind()
    codeless = conn.execute(sa.text(
        'SELECT COUNT(*) FROM products WHERE code IS NULL')).scalar()
    if codeless:
        raise RuntimeError(
            '%d product(s) have no code. Downgrading would restore NOT NULL with '
            'nowhere to put them. Assign codes deliberately, then retry.' % codeless)
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.alter_column('code', existing_type=sa.String(length=50),
                              nullable=False)
```

- [ ] **Step 5: Make the ORM column match**

In `app/products/models.py`, change:

```python
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
```

to:

```python
    # Optional since prodcode_0001 (owner, 2026-09-08): the code is retired from
    # every screen, but the column and its recorded values stay so the decision is
    # reversible. unique=True is KEPT -- SQLite allows multiple NULLs under a
    # unique index, so new products collide with nothing while the 555 existing
    # codes stay unique.
    code = db.Column(db.String(50), unique=True, nullable=True, index=True)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_product_code_retired.py -q --no-cov`
Expected: PASS (7 passed)

- [ ] **Step 7: Verify the migration on a copy of the live database**

```bash
S="$TMPDIR/prodcode"; mkdir -p "$S"
cp instance/philgen.db "$S/check.db"
python -c "
import sqlite3
c = sqlite3.connect(r'$S/check.db')
print('rows      ', c.execute('select count(*) from products').fetchone()[0])
print('with code ', c.execute(\"select count(*) from products where code is not null\").fetchone()[0])
print('indexes   ', sorted(r[1] for r in c.execute('PRAGMA index_list(products)')))
print('fks       ', len(c.execute('PRAGMA foreign_key_list(products)').fetchall()))
"
SQLALCHEMY_DATABASE_URI="sqlite:///$S/check.db" flask db upgrade
python -c "
import sqlite3
c = sqlite3.connect(r'$S/check.db')
print('rows      ', c.execute('select count(*) from products').fetchone()[0])
print('with code ', c.execute(\"select count(*) from products where code is not null\").fetchone()[0])
print('indexes   ', sorted(r[1] for r in c.execute('PRAGMA index_list(products)')))
print('fks       ', len(c.execute('PRAGMA foreign_key_list(products)').fetchall()))
print('integrity ', c.execute('PRAGMA integrity_check').fetchone()[0])
print('fk check  ', c.execute('PRAGMA foreign_key_check').fetchall() or 'clean')
"
```

Expected: row count, code count, index list and foreign-key count **identical before and after**; `integrity ok`; `fk check clean`. The unique index on `code` must still be present — if it is gone, stop: the rebuild has dropped the constraint this change depends on keeping.

- [ ] **Step 8: Apply it locally and commit**

```bash
flask db upgrade
flask db current
git add migrations/versions/prodcode_0001_product_code_optional.py \
        app/products/models.py tests/integration/test_product_code_retired.py
git commit -m "feat(products): the product code becomes optional"
```

---

## Task 2: The product form and list stop showing it

**Files:**
- Modify: `app/products/forms.py`, `app/products/views.py`, `app/products/templates/products/*.html`
- Test: `tests/integration/test_product_code_retired.py`

**Interfaces:**
- Consumes: the nullable column from Task 1.
- Produces: products created through the form have `code=None`; the list is ordered by `name`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_product_code_retired.py`:

```python
class TestTheProductScreens:
    """The owner's rule is that the code is not visible ANYWHERE in the app, and
    the product's own screens are where it was most prominent."""

    def _login(self, client, user, branch):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = branch.id

    def test_the_form_does_not_offer_a_code_field(self, client, admin_user,
                                                  main_branch, db_session):
        """Scoped to the INPUT, not the word: `code` appears in this page for the
        unit-of-measure and account selects, which must keep working."""
        import re
        self._login(client, admin_user, main_branch)
        html = client.get('/products/create').data.decode()
        assert not re.search(r'<input[^>]*name="code"', html)

    def test_the_customer_code_field_survives(self, client, admin_user,
                                              main_branch, db_session):
        """CONTROL. customer_code is the CUSTOMER's own SKU -- a different field
        that stays, and the one most likely to be deleted by a careless sweep."""
        import re
        self._login(client, admin_user, main_branch)
        html = client.get('/products/create').data.decode()
        assert re.search(r'<input[^>]*name="customer_code"', html)

    def test_a_product_created_through_the_form_has_no_code(self, client, admin_user,
                                                            main_branch, db_session):
        self._login(client, admin_user, main_branch)
        client.post('/products/create', data={
            'name': 'FORM CREATED ITEM', 'is_active': 'y'}, follow_redirects=True)
        p = Product.query.filter_by(name='FORM CREATED ITEM').first()
        assert p is not None, 'the form refused to save without a code'
        assert p.code is None

    def test_the_list_does_not_show_a_code_column(self, client, admin_user,
                                                  main_branch, db_session):
        self._login(client, admin_user, main_branch)
        html = client.get('/products').data.decode()
        assert '<th>Code</th>' not in html
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_product_code_retired.py -q --no-cov -k ProductScreens`
Expected: FAIL — the input is present and the form refuses to save without a code.

- [ ] **Step 3: Remove the form field**

In `app/products/forms.py`, delete the `code` field and its validators. **Leave `customer_code` exactly as it is.** Add a short comment where the field was, naming `prodcode_0001` and saying the column is still there.

- [ ] **Step 4: Stop the views reading it**

In `app/products/views.py`:

- `Product.query.order_by(Product.code)` → `Product.query.order_by(Product.name)`. The list was ordered by a column the user can no longer see, which would look arbitrary.
- `code=form.code.data.strip()` in the create path → drop the assignment entirely, so new products get `None`.
- `log_create('products', p.id, p.code, p.to_dict())` → identify by `p.name`. The audit log is user-facing; identifying a record by a code nobody can see makes the entry unreadable.
- Any payload dict emitting `'code': p.code` for a picker → drop the key.
- Leave `to_dict()` alone for now — it is a serialiser, not a screen, and Task 5 handles the payloads that feed pickers.

- [ ] **Step 5: Remove it from the templates**

In `app/products/templates/products/`: drop the code column header and cell from the list, and the code field from the form. Check `detail.html` if one exists. Do **not** touch `customer_code`, `unit_of_measure.code` or `account.code`.

- [ ] **Step 6: Run the tests**

```
python -m pytest tests/integration/test_product_code_retired.py -q --no-cov
python -m pytest tests/ -q --no-cov -k product -p no:cacheprovider
```

Existing product tests will fail where they assert a code is required or rendered. Each is a test that encoded the old rule: **update it to pin the new one, and say so in your report** — do not delete it and do not weaken it to pass.

- [ ] **Step 7: Commit**

```bash
git add app/products/ tests/integration/test_product_code_retired.py
git commit -m "feat(products): retire the code from the product screens"
```

---

## Task 3: Purchase requisitions

**Files:**
- Modify: `app/purchase_requests/models.py` (lines ~259, ~305), `app/purchase_requests/allocation.py` (~465), `app/purchase_requests/templates/purchase_requests/print_preprinted.html` (~153)
- Test: `tests/integration/test_product_code_retired.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2 beyond the column being optional.
- Produces: requisition payloads and the pre-printed overlay stop emitting a product code.

- [ ] **Step 1: Write the failing test**

```python
class TestPurchasingDocumentsDoNotShowIt:
    """32 references across the purchasing area, done first at the owner's
    instruction. Each document is asserted separately so a failure names which
    one regressed."""

    def test_the_requisition_overlay_prints_the_name_only(self, client, db_session,
                                                          admin_user, main_branch):
        # Build a requisition with a coded product, render the pre-printed
        # overlay, and assert the code does not appear while the name does.
        # Use the fixtures the existing PR print tests use; see
        # tests/integration/test_p2p_preprinted_print.py for the pattern.
        raise NotImplementedError(
            'Write this against the existing PR overlay fixtures. It must assert '
            'the NAME is present and the CODE absent -- a test that only asserts '
            'absence would pass on a blank page.')
```

Replace that stub with a real test modelled on `tests/integration/test_p2p_preprinted_print.py`, which already builds a requisition and renders the overlay. **The positive half is not optional**: asserting only that the code is gone would pass if the whole line vanished.

- [ ] **Step 2: Run it to make sure it fails**

- [ ] **Step 3: Change the overlay**

`print_preprinted.html:153`:

```jinja
{%- elif col.key == 'product' -%}{% if item.product %}{{ item.product.code ~ ' — ' ~ item.product.name }}{% else %}{{ '' }}{% endif %}
```

becomes:

```jinja
{%- elif col.key == 'product' -%}{{ item.product.name if item.product else '' }}
```

- [ ] **Step 4: Drop the payload keys**

In `models.py` (~259 and ~305) and `allocation.py` (~465), remove the `'product_code': ...` entries. These feed the line-item widget and the requisition picker; the consuming JavaScript reads `product_name` alongside and must be checked for a `product_code` fallback (see Task 5's note on the receiving-report picker, which has one).

- [ ] **Step 5: Run the tests, then commit**

```
python -m pytest tests/ -q --no-cov -m purchase_requests -p no:cacheprovider
git commit -m "feat(pr): the requisition stops showing the product code"
```

---

## Task 4: Purchase orders

**Files:**
- Modify: `app/purchase_orders/models.py` (~225 snapshot, ~303 to_dict), `app/purchase_orders/templates/purchase_orders/form.html` (~573)
- Test: `tests/integration/test_product_code_retired.py`

- [ ] **Step 1: Write the failing test** — the order's overlay and line table show the name, not the code. Positive and negative halves both required, as in Task 3.

- [ ] **Step 2: Run it to make sure it fails**

- [ ] **Step 3: The picker's display string**

`form.html:573`:

```js
? escHtml(row.product_code + ': ' + row.product_name)
```

becomes:

```js
? escHtml(row.product_name)
```

Check the surrounding ternary — it exists because a row may have no product name, and that branch must still work.

- [ ] **Step 4: The snapshot**

`models.py:225` is `snapshot_line_extras`, which feeds `DocumentRevision`. Stop emitting `product_code` for **new** snapshots. **Do not migrate or rewrite existing snapshot JSON** — those record what a revision actually carried.

`models.py:303` is `to_dict`, a picker/API payload. Drop the key.

- [ ] **Step 5: Run the tests, then commit**

```
python -m pytest tests/ -q --no-cov -m purchase_orders -p no:cacheprovider
git commit -m "feat(po): the order stops showing the product code"
```

---

## Task 5: Receiving reports — including the journal entry

**Files:**
- Modify: `app/receiving_reports/models.py` (~181), `app/receiving_reports/stock_posting.py` (77-78), `app/receiving_reports/templates/receiving_reports/form.html` (~150, ~176, ~200, ~351)
- Test: `tests/integration/test_product_code_retired.py`

**This task carries the one change that is not cosmetic.** Read the whole task before starting.

- [ ] **Step 1: Write the failing tests**

Two things need pinning here, and the second is the important one:

```python
    def test_the_receipt_picker_shows_the_name_only(self, client, db_session,
                                                    admin_user, main_branch):
        ...

    def test_the_stock_journal_entry_describes_the_product_by_name(
            self, client, db_session, admin_user, main_branch):
        """stock_posting writes the product into the JOURNAL ENTRY's line
        description -- a permanent accounting record, not a screen. Approving a
        receipt of a tracked product must now describe it by name.

        Build a tracked product with a standard cost, approve a receipt, and read
        the JE line descriptions back. Model the setup on
        tests/integration/test_receiving_report_stock_posting.py, which already
        assigns the inventory and GRNI control accounts.
        """
        ...
```

- [ ] **Step 2: Run them to make sure they fail**

- [ ] **Step 3: The journal entry description**

`stock_posting.py:77-78`:

```python
        _add_line(je, n, inv_account.id, f'{li.product.code} received', net_amount, ZERO); n += 1
        _add_line(je, n, grni_account.id, f'{li.product.code} accrued', ZERO, net_amount); n += 1
```

becomes:

```python
        # The product's NAME, not its code: the code is retired from every surface
        # (owner, 2026-09-08) and this text lands in the general ledger, where an
        # identifier nobody can look up is worse than none. Journal entries already
        # posted keep the text they were written with -- they record what was
        # booked, and rewriting them would falsify the books.
        _add_line(je, n, inv_account.id, f'{li.product.name} received', net_amount, ZERO); n += 1
        _add_line(je, n, grni_account.id, f'{li.product.name} accrued', ZERO, net_amount); n += 1
```

- [ ] **Step 4: The picker fallback**

`form.html:200` reads:

```js
const item = r.product_name || r.product_code || '';
```

The code is a **fallback** here, not a prefix. Removing it must not leave a line blank when a product has no name — check whether that is reachable (a product's `name` is NOT NULL, so it is not) and simplify to `r.product_name || ''`, with a comment saying why the fallback was safe to drop.

`form.html:351` prefixes the code in the pull picker; drop the prefix, keeping the ternary's no-name branch intact.

`form.html:150` and `~176` carry `product_code` through the payload and index; remove both, and check nothing else reads the key.

- [ ] **Step 5: The payload**

`models.py:181` resolves the code through the order line or the product. Drop the key.

- [ ] **Step 6: Run the tests, then commit**

```
python -m pytest tests/ -q --no-cov -m receiving_reports -p no:cacheprovider
git commit -m "feat(rr): the receipt stops showing the product code, including in the JE"
```

---

## Task 6: Payables, disbursements and purchase memos

**Files:**
- Modify: `app/accounts_payable/` (3 templates), `app/cash_disbursements/` (3 templates), `app/purchase_memos/` (2 templates), `app/accounts_payable/particulars.py` if it names a code
- Test: `tests/integration/test_product_code_retired.py`

- [ ] **Step 1: Find every remaining purchasing reference**

```bash
grep -rn "product\.code\|product_code" \
  app/accounts_payable app/cash_disbursements app/purchase_memos app/purchase_billing.py \
  --include=*.py --include=*.html | grep -v __pycache__
```

Work from that list. It is short; the earlier tasks removed the rest.

- [ ] **Step 2: Write a failing test per document** that renders each and asserts the name shows and the code does not.

- [ ] **Step 3: Apply the changes, keeping `account.code` and `uom.code` intact.** Those are different fields on different models and must keep rendering — a careless `product_code` sweep is the likeliest way to break a voucher's account column.

- [ ] **Step 4: Run and commit**

```
python -m pytest tests/ -q --no-cov -k "accounts_payable or cash_disbursement or purchase_memo" -p no:cacheprovider
git commit -m "feat(ap,cdv): the vouchers stop showing the product code"
```

---

## Task 7: Verification

- [ ] **Step 1: Confirm the purchasing area is clean**

```bash
grep -rn "product\.code\|product_code" \
  app/purchase_requests app/purchase_orders app/receiving_reports \
  app/accounts_payable app/cash_disbursements app/purchase_memos app/purchase_billing.py \
  --include=*.py --include=*.html | grep -v __pycache__
```

Expected: no hits. Any that remain must be named in the report with a reason.

- [ ] **Step 2: Run the full suite**

`python -m pytest -q --no-cov`

If it is killed for memory, run it in slices and record the slicing so the coverage argument is checkable — see `.git/sdd/progress.md` for the pattern used on the receiving-report work.

- [ ] **Step 3: Browser pass**

Nothing in this repository executes the pickers' JavaScript, so Tasks 4 and 5's display changes have no automated cover. On the dev server:

1. `/purchase-orders/create` — the product picker lists names alone
2. `/receiving-reports/create` — both pickers, including **+ Add Item Without PO**
3. Print a PO and an RR overlay — the product column shows the name
4. `/products` — no code column, sorted by name; create one and confirm it saves

- [ ] **Step 4: Record what Phase 2 still holds**

Add a short note to this file listing the modules still showing the code — sales, inventory, manufacturing, reports — with the reference count at the time, so the next plan starts from a measured position rather than a fresh sweep.

---

## Self-Review

**Spec coverage**

| Owner requirement | Task |
|---|---|
| Approach C — optional, not deleted | 1 (nullable, index and values kept) |
| Not visible anywhere in the app | 2-6, verified in 7 |
| Purchasing area first | 3-6 precede Phase 2 entirely |
| Existing codes survive | 1 (no data change), verified on a live copy |
| History untouched | 4 (snapshots), 5 (journal entries) |

**Risks named rather than hidden**

- The journal-entry description (Task 5) changes a permanent accounting record's text for new postings. Called out rather than folded in with the display changes.
- `product_code` appears in stored revision snapshots. Left alone deliberately; a reader may mistake that for an oversight, so both the task and the constraint say so.
- The string `code` is shared with `customer_code`, `unit_of_measure.code` and `account.code`. Every task that greps for it carries the warning, and Task 2 has an explicit control test for `customer_code`.

**Placeholders:** Task 3 Step 1 and Task 5 Step 1 deliberately carry `NotImplementedError` stubs rather than invented test bodies, because both must be written against existing fixtures whose exact shape belongs to the file they live in. Every other step contains the code to use.
