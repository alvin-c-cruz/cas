# Named Print Layouts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Purchase Orders have many named pre-printed layouts, with each workstation choosing which one it prints with, so two purchasers on different printers stop overwriting each other's alignment.

**Architecture:** Two new tables (`print_layouts`, `print_layout_device_prefs`) behind the existing `get_layout()` / `save_layout()` signatures in `app/common/preprinted_base.py`. Resolution falls through device pref → default row → legacy `app_settings` key → hardcoded defaults, so the feature is inert until rows exist. A `cas_device_id` cookie identifies the workstation; the selection itself lives server-side.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, SQLite, Alembic (hand-written migrations), pytest, Playwright for designer e2e.

**Spec:** `docs/design/2026-09-18-named-print-layouts-design.md` — read it first; this plan argues from it.

## Global Constraints

- **Time:** never naive `datetime.now()`. Use `ph_now()` from `app.utils`.
- **Migrations are hand-written.** `Migrate()` has no `render_as_batch`, so autogenerate emits `ALTER`s SQLite cannot run. `create_table` needs no batch wrapper. **Name every FK constraint explicitly** — an unnamed FK is legal in `create_table` but a later batch rebuild cannot reproduce it.
- **Verify the migration against a copy of a real database**, not a `create_all()` test DB. Worked example: `tools/verify_r08_migration.py`.
- **Never hardcode a GL account code.** Not applicable here, but do not introduce one.
- **Audit through `app/audit/utils.py`**, using `get_changes(old_obj, new_data, fields)` — never `old_values={}`. Verify audit rows in CRUD tests by exercising the real HTTP route.
- **UI verbs:** transactions use "Enter"; reference/master records use "Create". Layouts are configuration — use "Save as…", "Rename", "Delete", never "New".
- **Absence assertions must be scoped.** Inline `<style>`/JS text leaks into the response, so assert on the applied attribute (`class="pp-layout-picker"`), never a bare class name.
- **Test markers must be registered** in `pytest.ini`. Use the existing `purchase_orders` marker; do not invent one.
- `scope_id` is `NOT NULL`, `0` meaning unscoped. Never nullable — SQLite treats NULLs as distinct in UNIQUE.
- `doc_type` for this build is exactly `'purchase_orders'` (matches the audit module name).
- **Werkzeug is 3.1.3, Flask 3.1.0.** The test client's cookie API is `client.set_cookie(key, value)` and `client.get_cookie(key) -> Cookie | None`. `client.cookie_jar` does NOT exist (removed in Werkzeug 2.3) and `set_cookie` no longer takes a positional domain. Verified in this worktree, not assumed.
- `AppSettings` lives at `app/settings.py` — `from app.settings import AppSettings`. There is no `app/settings/models.py`.

---

### Task 1: Tables and constraints

**Files:**
- Create: `app/print_layouts/__init__.py`
- Create: `app/print_layouts/models.py`
- Create: `migrations/versions/prnlay_0001_print_layouts.py`
- Test: `tests/integration/test_print_layout_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PrintLayout` (fields `id, doc_type, scope_id, name, payload, is_default, created_by_id, created_at, updated_by_id, updated_at`) and `PrintLayoutDevicePref` (`id, device_id, doc_type, scope_id, layout_id, label, updated_at`), both importable from `app.print_layouts.models`.

- [ ] **Step 1: Write the failing test**

```python
"""The two constraints that carry the design: one name per scope, one default per scope."""
import pytest
from sqlalchemy.exc import IntegrityError
from app import db
from app.print_layouts.models import PrintLayout

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _layout(name, is_default=False, scope_id=1):
    return PrintLayout(doc_type='purchase_orders', scope_id=scope_id, name=name,
                       payload='{}', is_default=is_default)


def test_two_layouts_cannot_share_a_name_in_one_scope(db_session):
    db_session.add(_layout('Purchasing - LX-310')); db_session.commit()
    db_session.add(_layout('Purchasing - LX-310'))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_the_same_name_is_fine_in_a_different_scope(db_session):
    db_session.add(_layout('Purchasing - LX-310', scope_id=1))
    db_session.add(_layout('Purchasing - LX-310', scope_id=2))
    db_session.commit()
    assert PrintLayout.query.count() == 2


def test_only_one_default_per_scope(db_session):
    """A partial unique index, not application code. Two defaults makes 'the default row'
    unanswerable and the answer varies by row order."""
    db_session.add(_layout('A', is_default=True)); db_session.commit()
    db_session.add(_layout('B', is_default=True))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_many_non_defaults_are_fine(db_session):
    db_session.add(_layout('A', is_default=True))
    db_session.add(_layout('B'))
    db_session.add(_layout('C'))
    db_session.commit()
    assert PrintLayout.query.count() == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_print_layout_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.print_layouts'`

- [ ] **Step 3: Write the models**

`app/print_layouts/__init__.py` is empty. `app/print_layouts/models.py`:

```python
"""Named pre-printed layouts, and which layout each workstation prints with.

Configuration, not transactions — which is why neither table carries `branch_id`.
The branch IS `scope_id`, generalised so cd_check can later scope by cash account
without a schema change.

`scope_id` is NOT NULL with 0 meaning unscoped: SQLite treats NULLs as distinct in
a UNIQUE constraint, so a nullable column would let two rows share
(doc_type, NULL, 'Default') and defeat the uniqueness silently.
"""
from app import db
from app.utils import ph_now


class PrintLayout(db.Model):
    __tablename__ = 'print_layouts'
    __table_args__ = (
        db.UniqueConstraint('doc_type', 'scope_id', 'name', name='uq_print_layouts_name'),
        # Partial unique index: at most one default per scope. Enforced by the
        # database because resolution asks for "the default row" and two of them
        # would resolve by row order.
        db.Index('uq_print_layouts_one_default', 'doc_type', 'scope_id',
                 unique=True, sqlite_where=db.text('is_default = 1')),
    )

    id = db.Column(db.Integer, primary_key=True)
    doc_type = db.Column(db.String(40), nullable=False, index=True)
    scope_id = db.Column(db.Integer, nullable=False, default=0)
    name = db.Column(db.String(100), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=ph_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=ph_now, onupdate=ph_now)

    def __repr__(self):
        return f'<PrintLayout {self.doc_type}/{self.scope_id} {self.name!r}>'


class PrintLayoutDevicePref(db.Model):
    """Which layout ONE WORKSTATION prints with. Deliberately no user_id: a layout
    belongs to a printer, and a workstation prints to one printer, so the machine's
    choice is the right answer for whoever sits at it."""
    __tablename__ = 'print_layout_device_prefs'
    __table_args__ = (
        db.UniqueConstraint('device_id', 'doc_type', 'scope_id',
                            name='uq_print_layout_device_prefs'),
    )

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), nullable=False, index=True)
    doc_type = db.Column(db.String(40), nullable=False)
    scope_id = db.Column(db.Integer, nullable=False, default=0)
    # SET NULL, never CASCADE: deleting a layout must strand the workstation on the
    # default, not delete the workstation's row.
    layout_id = db.Column(db.Integer, db.ForeignKey('print_layouts.id', ondelete='SET NULL'),
                          nullable=True)
    label = db.Column(db.String(100), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=ph_now, onupdate=ph_now)

    layout = db.relationship('PrintLayout')
```

Register the model module so `create_all()` and Alembic see it — add to the imports in `app/__init__.py` alongside the other model imports (search for `from app.attachments import models` and follow that pattern exactly).

- [ ] **Step 4: Write the migration**

`migrations/versions/prnlay_0001_print_layouts.py`:

```python
"""Named print layouts, and the per-workstation selection.

Purely ADDITIVE — two new tables, nothing altered. create_table needs no batch
wrapper; every FK is NAMED so a later batch rebuild can reproduce it.

Revision ID: prnlay_0001
Revises: apamd_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'prnlay_0001'
down_revision = 'apamd_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'print_layouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doc_type', sa.String(length=40), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_print_layouts'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name='fk_print_layouts_created_by'),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], name='fk_print_layouts_updated_by'),
        sa.UniqueConstraint('doc_type', 'scope_id', 'name', name='uq_print_layouts_name'),
    )
    op.create_index('ix_print_layouts_doc_type', 'print_layouts', ['doc_type'])
    # Partial unique index -- raw DDL because Alembic's create_index has no
    # cross-dialect partial-index argument and this is SQLite only.
    op.execute('CREATE UNIQUE INDEX uq_print_layouts_one_default '
               'ON print_layouts (doc_type, scope_id) WHERE is_default = 1')

    op.create_table(
        'print_layout_device_prefs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.String(length=64), nullable=False),
        sa.Column('doc_type', sa.String(length=40), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('layout_id', sa.Integer(), nullable=True),
        sa.Column('label', sa.String(length=100), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_print_layout_device_prefs'),
        sa.ForeignKeyConstraint(['layout_id'], ['print_layouts.id'],
                                name='fk_print_layout_device_prefs_layout',
                                ondelete='SET NULL'),
        sa.UniqueConstraint('device_id', 'doc_type', 'scope_id',
                            name='uq_print_layout_device_prefs'),
    )
    op.create_index('ix_print_layout_device_prefs_device', 'print_layout_device_prefs',
                    ['device_id'])


def downgrade():
    op.drop_index('ix_print_layout_device_prefs_device',
                  table_name='print_layout_device_prefs')
    op.drop_table('print_layout_device_prefs')
    op.execute('DROP INDEX IF EXISTS uq_print_layouts_one_default')
    op.drop_index('ix_print_layouts_doc_type', table_name='print_layouts')
    op.drop_table('print_layouts')
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/integration/test_print_layout_models.py -q`
Expected: PASS, 4 tests.

If `test_only_one_default_per_scope` fails, the `sqlite_where` partial index did not reach `create_all()` — the test DB is built from the models, not the migration, so the model's `db.Index(..., sqlite_where=...)` must be correct independently of the migration's raw DDL. Both must exist.

- [ ] **Step 6: Verify the migration against a copy of the REAL database**

```bash
cp cas/instance/philgen.db /tmp/verify-prnlay.db
cd cas && SQLALCHEMY_DATABASE_URI="sqlite:////tmp/verify-prnlay.db" flask db upgrade
SQLALCHEMY_DATABASE_URI="sqlite:////tmp/verify-prnlay.db" flask db current   # expect prnlay_0001
python -c "
import sqlite3; c = sqlite3.connect('/tmp/verify-prnlay.db')
print(c.execute(\"select name from sqlite_master where name like 'print_layout%'\").fetchall())
print(c.execute(\"select sql from sqlite_master where name='uq_print_layouts_one_default'\").fetchone())
"
```
Expected: both tables plus both indexes present; the partial index SQL contains `WHERE is_default = 1`. Then `flask db downgrade` and confirm both tables are gone.

- [ ] **Step 7: Commit**

```bash
git add app/print_layouts migrations/versions/prnlay_0001_print_layouts.py \
        tests/integration/test_print_layout_models.py app/__init__.py
git commit -m "feat(print-layouts): tables for named layouts and per-device selection"
```

---

### Task 2: Workstation identity

**Files:**
- Create: `app/print_layouts/device.py`
- Modify: `app/__init__.py` (register the after_request that sets the cookie)
- Test: `tests/integration/test_print_layout_device_cookie.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `current_device_id() -> str | None` (reads the request cookie, no side effects) and `DEVICE_COOKIE = 'cas_device_id'`, both from `app.print_layouts.device`.

- [ ] **Step 1: Write the failing test**

```python
"""The workstation is a cookie. Absent or cleared must degrade, never fail."""
import pytest
from app.print_layouts.device import DEVICE_COOKIE, current_device_id

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def test_a_first_visit_is_issued_a_device_id(client):
    resp = client.get('/login')
    assert resp.status_code == 200
    assert client.get_cookie(DEVICE_COOKIE) is not None, 'no device cookie set'


def test_the_device_id_is_stable_across_requests(client):
    client.get('/login')
    first = client.get_cookie(DEVICE_COOKIE).value
    client.get('/login')
    second = client.get_cookie(DEVICE_COOKIE).value
    assert first == second, 'a new id per request would make the pref unfindable'


def test_no_cookie_reads_as_none_rather_than_raising(app):
    with app.test_request_context('/'):
        assert current_device_id() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_print_layout_device_cookie.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.print_layouts.device'`

- [ ] **Step 3: Implement**

`app/print_layouts/device.py`:

```python
"""Identify the WORKSTATION, not the user.

A layout belongs to a printer and a workstation prints to one printer, so the
machine is the right thing to remember a layout choice against. The cookie holds
only an opaque id; the choice itself is a server-side row, so an admin can see
what each machine is set to and a cleared cookie degrades to the default rather
than to something wrong.

Deliberately NOT company-scoped, unlike cas_philgen / cas_ric: philgen and ric on
one machine are the same physical printer, and the pref rows live in each
company's own database, so nothing leaks.
"""
import uuid

from flask import request

DEVICE_COOKIE = 'cas_device_id'
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 5   # five years; a desk outlives a session


def current_device_id():
    """This workstation's id, or None when the cookie is absent or malformed."""
    raw = (request.cookies.get(DEVICE_COOKIE) or '').strip()
    return raw if raw and len(raw) <= 64 else None


def new_device_id():
    return uuid.uuid4().hex


def attach_device_cookie(response):
    """Issue an id to a workstation that has none. Registered as an after_request."""
    if current_device_id() is not None:
        return response
    if request.cookies.get(DEVICE_COOKIE) is not None:
        pass   # present but malformed -- reissue
    response.set_cookie(
        DEVICE_COOKIE, new_device_id(),
        max_age=DEVICE_COOKIE_MAX_AGE, httponly=True, samesite='Lax',
        secure=bool(request.is_secure),
    )
    return response
```

In `app/__init__.py`, register it next to the existing `add_security_headers` after_request:

```python
    from app.print_layouts.device import attach_device_cookie
    app.after_request(attach_device_cookie)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/integration/test_print_layout_device_cookie.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add app/print_layouts/device.py app/__init__.py \
        tests/integration/test_print_layout_device_cookie.py
git commit -m "feat(print-layouts): issue a stable per-workstation device id"
```

---

### Task 3: Resolution chain

**Files:**
- Create: `app/print_layouts/service.py`
- Modify: `app/common/preprinted_base.py:520-540` (`get_layout` gains `device_id`)
- Test: `tests/integration/test_print_layout_resolution.py`

**Interfaces:**
- Consumes: `PrintLayout`, `PrintLayoutDevicePref` (Task 1).
- Produces, all from `app.print_layouts.service`: `resolve_layout(doc_type, scope_id, device_id=None) -> PrintLayout | None` (the row that wins); `resolve_payload(doc_type, scope_id, device_id=None) -> str | None` (its raw JSON, or `None` when no row applies, so the caller falls through to legacy/defaults); `list_layouts(doc_type, scope_id) -> list[PrintLayout]` in dropdown order; `default_layout_row(doc_type, scope_id) -> PrintLayout | None`.

- [ ] **Step 1: Write the failing test**

```python
"""Resolution order: device pref -> is_default -> first row -> legacy key -> hardcoded.
Never a hard failure at any step."""
import json
import pytest
from app import db
from app.settings import AppSettings
from app.print_layouts.models import PrintLayout, PrintLayoutDevicePref
from app.print_layouts.service import resolve_payload
from app.purchase_orders.preprinted_layout import get_layout

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

DOC, SCOPE = 'purchase_orders', 1


def _row(name, payload, is_default=False):
    r = PrintLayout(doc_type=DOC, scope_id=SCOPE, name=name,
                    payload=json.dumps(payload), is_default=is_default)
    db.session.add(r); db.session.commit()
    return r


def test_no_rows_and_no_legacy_key_returns_none(db_session):
    assert resolve_payload(DOC, SCOPE, 'dev1') is None


def test_the_default_row_wins_when_the_device_has_no_pref(db_session):
    _row('Default', {'marker': 'default'}, is_default=True)
    _row('Other', {'marker': 'other'})
    assert json.loads(resolve_payload(DOC, SCOPE, 'dev1'))['marker'] == 'default'


def test_the_device_pref_beats_the_default(db_session):
    _row('Default', {'marker': 'default'}, is_default=True)
    other = _row('Other', {'marker': 'other'})
    db_session.add(PrintLayoutDevicePref(device_id='dev1', doc_type=DOC,
                                         scope_id=SCOPE, layout_id=other.id))
    db_session.commit()
    assert json.loads(resolve_payload(DOC, SCOPE, 'dev1'))['marker'] == 'other'
    # a DIFFERENT workstation is unaffected
    assert json.loads(resolve_payload(DOC, SCOPE, 'dev2'))['marker'] == 'default'


def test_a_pref_pointing_at_a_deleted_layout_falls_back(db_session):
    """AC 4. ON DELETE SET NULL leaves the pref row; resolution must not blow up."""
    _row('Default', {'marker': 'default'}, is_default=True)
    other = _row('Other', {'marker': 'other'})
    db_session.add(PrintLayoutDevicePref(device_id='dev1', doc_type=DOC,
                                         scope_id=SCOPE, layout_id=other.id))
    db_session.commit()
    db_session.delete(other); db_session.commit()
    assert json.loads(resolve_payload(DOC, SCOPE, 'dev1'))['marker'] == 'default'


def test_get_layout_reads_through_to_the_legacy_key(db_session):
    """With no rows at all, behaviour is exactly as before this feature."""
    legacy = get_layout(branch_id=SCOPE)
    legacy['page']['fontFamily'] = 'Arial, sans-serif'
    AppSettings.set_setting('po_preprinted_layout:1', json.dumps(legacy), 'system')
    assert get_layout(branch_id=SCOPE)['page']['fontFamily'] == 'Arial, sans-serif'


def test_a_row_beats_the_legacy_key(db_session):
    legacy = get_layout(branch_id=SCOPE)
    legacy['page']['fontFamily'] = 'Arial, sans-serif'
    AppSettings.set_setting('po_preprinted_layout:1', json.dumps(legacy), 'system')
    row = dict(legacy); row['page'] = {'fontFamily': 'Georgia, serif'}
    _row('Default', row, is_default=True)
    assert get_layout(branch_id=SCOPE)['page']['fontFamily'] == 'Georgia, serif'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_print_layout_resolution.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.print_layouts.service'`

- [ ] **Step 3: Implement the service**

`app/print_layouts/service.py`:

```python
"""Which stored layout applies, and the library listing behind the dropdowns.

Returns RAW payload strings. Sanitizing stays where it already is, in
preprinted_base.sanitize_layout, so there is exactly one place a layout is
validated no matter which store it came from.
"""
from app.print_layouts.models import PrintLayout, PrintLayoutDevicePref


def list_layouts(doc_type, scope_id):
    """The library for one scope, defaults first then by name -- the dropdown order."""
    return (PrintLayout.query
            .filter_by(doc_type=doc_type, scope_id=scope_id or 0)
            .order_by(PrintLayout.is_default.desc(), PrintLayout.name.asc())
            .all())


def default_layout_row(doc_type, scope_id):
    return PrintLayout.query.filter_by(doc_type=doc_type, scope_id=scope_id or 0,
                                       is_default=True).first()


def resolve_layout(doc_type, scope_id, device_id=None):
    """The PrintLayout that applies here, or None. Device pref, then default, then
    the first row. A pref whose layout was deleted holds layout_id NULL and falls
    through rather than raising -- that is AC 4."""
    scope_id = scope_id or 0
    if device_id:
        pref = PrintLayoutDevicePref.query.filter_by(
            device_id=device_id, doc_type=doc_type, scope_id=scope_id).first()
        if pref is not None and pref.layout is not None:
            return pref.layout
    row = default_layout_row(doc_type, scope_id)
    if row is not None:
        return row
    return (PrintLayout.query
            .filter_by(doc_type=doc_type, scope_id=scope_id)
            .order_by(PrintLayout.id.asc()).first())


def resolve_payload(doc_type, scope_id, device_id=None):
    row = resolve_layout(doc_type, scope_id, device_id)
    return row.payload if row is not None else None
```

- [ ] **Step 4: Wire it into `get_layout`**

In `app/common/preprinted_base.py`, `build_layout_api` gains a `doc_type` argument (default `audit_module`, so no caller changes), and `get_layout` becomes:

```python
    def get_layout(branch_id=None, device_id=None):
        """Current sanitized layout (defaults if unset or corrupt).

        Order: this workstation's chosen layout, then the scope's default layout,
        then the legacy app_settings key, then the declared defaults. Every step is
        fail-safe: the print page HOSTS the designer, so a raise here would leave a
        branch with no UI to fix its own layout with.
        """
        from app.print_layouts.service import resolve_payload
        stored = None
        try:
            stored = resolve_payload(doc_type, branch_id or 0, device_id)
        except Exception:  # noqa: BLE001 -- table may not exist pre-migration
            stored = None
        if stored is None:
            stored = AppSettings.get_setting(_layout_key(branch_id))
        if not stored:
            return sanitize_layout(copy.deepcopy(default_layout))
        try:
            return sanitize_layout(json.loads(stored))
        except Exception:  # noqa: BLE001 -- deliberately fail-safe
            return sanitize_layout(copy.deepcopy(default_layout))
```

The `except Exception` around `resolve_payload` is deliberate and matches the existing fail-safe contract: code deployed before its migration runs must still print.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/integration/test_print_layout_resolution.py -m purchase_orders -q`
Expected: PASS, 6 tests.

- [ ] **Step 6: Run the full purchase-orders suite for regressions**

Run: `python -m pytest -m purchase_orders -q`
Expected: all PASS. Any failure here means an existing caller of `get_layout` broke — the signature change must be additive.

- [ ] **Step 7: Commit**

```bash
git add app/print_layouts/service.py app/common/preprinted_base.py \
        tests/integration/test_print_layout_resolution.py
git commit -m "feat(print-layouts): resolve device pref -> default -> legacy key"
```

---

### Task 4: Migrate the existing layouts, and prove the sheets are identical

**Files:**
- Create: `migrations/versions/prnlay_0002_seed_po_layouts.py`
- Create: `tools/verify_print_layout_migration.py`
- Test: `tests/integration/test_print_layout_migration_fidelity.py`

**Interfaces:**
- Consumes: `PrintLayout` (Task 1), `get_layout` (Task 3).
- Produces: one `is_default` `PrintLayout` row per existing `po_preprinted_layout*` key.

**This is the task that matters.** A wrong result here costs a pad of pre-printed forms.

- [ ] **Step 1: Write the failing test**

```python
"""AC 6: printing a PO immediately before and after the migration must be IDENTICAL.

The payload is copied RAW, never re-sanitized. A stored layout is sanitized at READ
time against whatever the defaults currently are; sanitizing at WRITE time instead
would bake today's defaults into a value that was hand-aligned on paper months ago.
"""
import json
import pytest
from app import db
from app.settings import AppSettings
from app.print_layouts.models import PrintLayout
from app.purchase_orders.preprinted_layout import get_layout

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _seed_legacy(branch_id=1):
    """A layout with hand-aligned, non-default coordinates -- the realistic case."""
    lay = get_layout(branch_id=branch_id)
    lay['fields']['pr_number']['x'] = 48
    lay['fields']['pr_number']['w'] = 44
    raw = json.dumps(lay)
    AppSettings.set_setting(f'po_preprinted_layout:{branch_id}', raw, 'system')
    return raw


def test_the_migration_copies_the_payload_byte_for_byte(db_session):
    from app.print_layouts.migrate import seed_from_app_settings
    raw = _seed_legacy()
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    row = PrintLayout.query.filter_by(doc_type='purchase_orders', scope_id=1).one()
    assert row.payload == raw, 'payload was transformed on the way in'
    assert row.is_default is True


def test_get_layout_is_identical_before_and_after(db_session):
    from app.print_layouts.migrate import seed_from_app_settings
    _seed_legacy()
    before = get_layout(branch_id=1)
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    after = get_layout(branch_id=1)
    assert before == after


def test_the_unscoped_key_lands_on_scope_zero(db_session):
    from app.print_layouts.migrate import seed_from_app_settings
    lay = json.dumps(get_layout())
    AppSettings.set_setting('po_preprinted_layout', lay, 'system')
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    row = PrintLayout.query.filter_by(doc_type='purchase_orders', scope_id=0).one()
    assert row.name == 'Default'


def test_running_the_seed_twice_changes_nothing(db_session):
    """Migrations get re-run against restored databases. Idempotence is not optional."""
    from app.print_layouts.migrate import seed_from_app_settings
    _seed_legacy()
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')
    assert PrintLayout.query.count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_print_layout_migration_fidelity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.print_layouts.migrate'`

- [ ] **Step 3: Implement the seeding helper**

`app/print_layouts/migrate.py`:

```python
"""Copy existing app_settings layouts into print_layouts rows.

Lives in app/ rather than inside the migration file so it is importable and
testable. The migration calls it; so does the verification tool.
"""
from app import db
from app.settings import AppSettings
from app.print_layouts.models import PrintLayout


def _branch_label(branch_id):
    from app.branches.models import Branch
    branch = Branch.query.get(branch_id) if branch_id else None
    return f'Default - {branch.name}' if branch is not None else 'Default'


def seed_from_app_settings(doc_type, key_prefix):
    """One is_default row per existing `<key_prefix>` / `<key_prefix>:<id>` setting.

    Payload copied RAW. Idempotent: a scope that already has any row is skipped, so
    re-running against a restored database cannot duplicate or overwrite.
    """
    rows = AppSettings.query.filter(
        db.or_(AppSettings.key == key_prefix,
               AppSettings.key.like(f'{key_prefix}:%'))).all()
    created = 0
    for setting in rows:
        suffix = setting.key[len(key_prefix):].lstrip(':')
        try:
            scope_id = int(suffix) if suffix else 0
        except ValueError:
            continue    # not a scope key -- leave it alone
        exists = PrintLayout.query.filter_by(doc_type=doc_type, scope_id=scope_id).first()
        if exists is not None:
            continue
        db.session.add(PrintLayout(
            doc_type=doc_type, scope_id=scope_id,
            name=_branch_label(scope_id), payload=setting.value, is_default=True))
        created += 1
    db.session.commit()
    return created
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/integration/test_print_layout_migration_fidelity.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Write the data migration**

`migrations/versions/prnlay_0002_seed_po_layouts.py` — revision `prnlay_0002`, down_revision `prnlay_0001`. In `upgrade()`, call the helper through a Flask app context; in `downgrade()`, `DELETE FROM print_layouts WHERE doc_type = 'purchase_orders'`. The legacy `app_settings` keys are **not** touched in either direction.

- [ ] **Step 6: Verify against a copy of the REAL database**

Write `tools/verify_print_layout_migration.py`, modelled on `tools/verify_r08_migration.py`: open a copy of `instance/philgen.db`, record `get_layout(branch_id)` for every branch, run the migration, record it again, and assert equality — failing loudly with a diff if not.

```bash
cp cas/instance/philgen.db /tmp/verify-seed.db
cd cas && python tools/verify_print_layout_migration.py /tmp/verify-seed.db
```
Expected: `IDENTICAL for branch 1` and a non-zero row count. A diff here stops the feature.

- [ ] **Step 7: Commit**

```bash
git add app/print_layouts/migrate.py migrations/versions/prnlay_0002_seed_po_layouts.py \
        tools/verify_print_layout_migration.py \
        tests/integration/test_print_layout_migration_fidelity.py
git commit -m "feat(print-layouts): seed existing PO layouts, byte for byte"
```

---

### Task 5: Saving, renaming, deleting, and the delete permission

**Files:**
- Modify: `app/users/models.py` (add `can_delete_print_layout` beside `can_edit_print_layout`)
- Modify: `app/print_layouts/service.py` (write operations)
- Modify: `app/common/preprinted_base.py` (`save_layout` dual-writes)
- Test: `tests/integration/test_print_layout_writes.py`

**Interfaces:**
- Consumes: `list_layouts`, `resolve_layout` (Task 3).
- Produces, in `app.print_layouts.service`: `create_layout(doc_type, scope_id, name, payload, user) -> PrintLayout`, `rename_layout(layout_id, name) -> PrintLayout`, `delete_layout(layout_id) -> PrintLayout | None` (raises `ValueError` on the default), `set_device_layout(device_id, doc_type, scope_id, layout_id) -> PrintLayoutDevicePref`.
- Produces, in `app/common/preprinted_base.py`: `save_layout(raw, username, branch_id=None, layout_id=None)` — the existing function, one optional argument wider. There is no separate `save_payload`; saving goes through the same seam it always has.
- Produces, on `User`: `can_delete_print_layout -> bool`.

- [ ] **Step 1: Write the failing test**

```python
"""AC 1, 4 and 5, the dual-write, and who may delete."""
import json
import pytest
from app import db
from app.settings import AppSettings
from app.print_layouts.models import PrintLayout, PrintLayoutDevicePref
from app.print_layouts import service
from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

DOC, SCOPE = 'purchase_orders', 1


def _mk(name, is_default=False, marker='x'):
    r = PrintLayout(doc_type=DOC, scope_id=SCOPE, name=name, is_default=is_default,
                    payload=json.dumps({'marker': marker}))
    db.session.add(r); db.session.commit()
    return r


def test_two_named_layouts_coexist(db_session):
    """AC 1: neither purchaser overwrites the other."""
    service.create_layout(DOC, SCOPE, 'Angilyn - LX-310', json.dumps({'marker': 'a'}), None)
    service.create_layout(DOC, SCOPE, 'Purchasing - HP', json.dumps({'marker': 'b'}), None)
    names = [r.name for r in service.list_layouts(DOC, SCOPE)]
    assert names == ['Angilyn - LX-310', 'Purchasing - HP']


def test_renaming_does_not_move_any_selection(db_session):
    """AC 5: the pref holds layout_id, so a rename cannot repoint a workstation."""
    row = _mk('Old name')
    service.set_device_layout('dev1', DOC, SCOPE, row.id)
    service.rename_layout(row.id, 'New name')
    pref = PrintLayoutDevicePref.query.filter_by(device_id='dev1').one()
    assert pref.layout_id == row.id
    assert pref.layout.name == 'New name'


def test_deleting_a_selected_layout_leaves_printing_working(db_session):
    """AC 4: the workstation falls back to the default, and the pref row survives."""
    default = _mk('Default', is_default=True, marker='default')
    other = _mk('Other', marker='other')
    service.set_device_layout('dev1', DOC, SCOPE, other.id)
    service.delete_layout(other.id)
    pref = PrintLayoutDevicePref.query.filter_by(device_id='dev1').one()
    assert pref.layout_id is None
    resolved = service.resolve_layout(DOC, SCOPE, 'dev1')
    assert resolved.id == default.id


def test_the_default_layout_cannot_be_deleted(db_session):
    default = _mk('Default', is_default=True)
    with pytest.raises(ValueError):
        service.delete_layout(default.id)


def test_saving_the_default_also_writes_the_legacy_key(db_session):
    """Transitional dual-write: a rollback must keep alignment work done since the
    migration, not just the state at migration time."""
    from app.purchase_orders.preprinted_layout import get_layout, save_layout
    _mk('Default', is_default=True)
    lay = get_layout(branch_id=SCOPE)
    lay['fields']['pr_number']['x'] = 77
    save_layout(lay, 'admin', branch_id=SCOPE)
    legacy = json.loads(AppSettings.get_setting(f'po_preprinted_layout:{SCOPE}'))
    assert legacy['fields']['pr_number']['x'] == 77


def test_saving_a_NON_default_layout_leaves_the_legacy_key_alone(db_session):
    from app.purchase_orders.preprinted_layout import get_layout, save_layout
    _mk('Default', is_default=True)
    other = _mk('Other')
    AppSettings.set_setting(f'po_preprinted_layout:{SCOPE}', json.dumps({'marker': 'untouched'}),
                            'system')
    lay = get_layout(branch_id=SCOPE)
    save_layout(lay, 'admin', branch_id=SCOPE, layout_id=other.id)
    assert json.loads(AppSettings.get_setting(f'po_preprinted_layout:{SCOPE}'))['marker'] \
        == 'untouched'


@pytest.mark.parametrize('role,allowed', [
    ('admin', True), ('chief_accountant', True), ('accountant', False), ('staff', False),
    ('viewer', False), ('', False),
])
def test_who_may_delete_a_layout(role, allowed):
    """Narrower than can_edit_print_layout: delete is the one action with
    cross-machine blast radius. A blank/unknown role must fail closed."""
    assert User(role=role).can_delete_print_layout is allowed


@pytest.mark.parametrize('role,allowed', [
    ('admin', True), ('chief_accountant', True), ('accountant', True), ('staff', True),
    ('viewer', False),
])
def test_edit_access_is_unchanged(role, allowed):
    """This feature must not take away what staff can already do."""
    assert User(role=role).can_edit_print_layout is allowed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_print_layout_writes.py -q`
Expected: FAIL — `AttributeError: 'User' object has no attribute 'can_delete_print_layout'`

- [ ] **Step 3: Add the permission**

In `app/users/models.py`, directly after `can_edit_print_layout`:

```python
    @property
    def can_delete_print_layout(self):
        """Who may DELETE a named print layout. Narrower than editing one.

        Editing a layout changes one printer's alignment; deleting one strands
        every workstation pointing at it, which is why this is the only layout
        action restricted beyond `can_edit_print_layout`. The fallback is safe --
        a stranded workstation resolves to the scope default -- but it is silent,
        and a purchaser discovers it on paper.

        A WHITELIST, for the same reason as can_edit_print_layout: an
        unrecognised, new or blank role must fail closed rather than inherit the
        ability by not being named.
        """
        return self.role in ('admin', 'chief_accountant')
```

- [ ] **Step 4: Implement the write operations**

Append to `app/print_layouts/service.py`:

```python
def create_layout(doc_type, scope_id, name, payload, user):
    from app import db
    row = PrintLayout(doc_type=doc_type, scope_id=scope_id or 0, name=name.strip(),
                      payload=payload, is_default=False,
                      created_by_id=getattr(user, 'id', None),
                      updated_by_id=getattr(user, 'id', None))
    db.session.add(row); db.session.commit()
    return row


def rename_layout(layout_id, name):
    from app import db
    row = PrintLayout.query.get(layout_id)
    row.name = name.strip()
    db.session.commit()
    return row


def delete_layout(layout_id):
    """Refuse to delete the default: resolution step 2 would have nothing to answer
    with, and every stranded workstation would fall to an arbitrary first row."""
    from app import db
    row = PrintLayout.query.get(layout_id)
    if row is None:
        return None
    if row.is_default:
        raise ValueError('The default layout cannot be deleted. '
                         'Make another layout the default first.')
    db.session.delete(row); db.session.commit()
    return row


def set_device_layout(device_id, doc_type, scope_id, layout_id):
    from app import db
    scope_id = scope_id or 0
    pref = PrintLayoutDevicePref.query.filter_by(
        device_id=device_id, doc_type=doc_type, scope_id=scope_id).first()
    if pref is None:
        pref = PrintLayoutDevicePref(device_id=device_id, doc_type=doc_type,
                                     scope_id=scope_id)
        db.session.add(pref)
    pref.layout_id = layout_id
    db.session.commit()
    return pref
```

- [ ] **Step 5: Dual-write in `save_layout`**

In `app/common/preprinted_base.py`, `save_layout` gains `layout_id=None`. When `layout_id` is None it targets the scope's default row. It always writes the `print_layouts` row, and writes the legacy `app_settings` key **only when the target row is the default**, with a comment marking the dual-write as transitional and naming the release that removes it.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/integration/test_print_layout_writes.py -q`
Expected: PASS, 8 test functions / 17 cases counting the two parametrised ones.

- [ ] **Step 7: Commit**

```bash
git add app/users/models.py app/print_layouts/service.py app/common/preprinted_base.py \
        tests/integration/test_print_layout_writes.py
git commit -m "feat(print-layouts): save-as, rename, delete, dual-write, delete permission"
```

---

### Task 6: Routes

**Files:**
- Modify: `app/purchase_orders/views.py` (pass `device_id`; add four routes)
- Test: `tests/integration/test_print_layout_routes.py`

**Interfaces:**
- Consumes: everything from Tasks 2–5.
- Produces: `POST /purchase-orders/print-layout/save-as`, `/rename`, `/delete`, `/select`, all JSON, all CSRF-protected.

- [ ] **Step 1: Write the failing test**

```python
"""The four routes, and AC 2 + AC 3: the SELECTION belongs to the workstation, so it
survives logout and applies to whoever sits down next."""
import json
import pytest
from app import db
from app.audit.models import AuditLog
from app.print_layouts.models import PrintLayout, PrintLayoutDevicePref
from app.print_layouts.device import DEVICE_COOKIE
from app.print_layouts.service import resolve_layout
from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

SCOPE = 1


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _user(db_session, branch, username, role):
    u = User(username=username, email=username + '@test.com', full_name=username,
             role=role, is_active=True)
    u.set_password('testpass123')
    db_session.add(u); db_session.flush(); u.set_branches([branch]); db_session.commit()
    return u


def _mk(name, is_default=False, marker='x'):
    r = PrintLayout(doc_type='purchase_orders', scope_id=SCOPE, name=name,
                    is_default=is_default, payload=json.dumps({'marker': marker}))
    db.session.add(r); db.session.commit()
    return r


def test_save_as_creates_a_named_layout(client, db_session, main_branch):
    _mk('Default', is_default=True)
    _login(client, _user(db_session, main_branch, 'acct1', 'accountant'), main_branch)
    resp = client.post('/purchase-orders/print-layout/save-as',
                       json={'name': 'Purchasing - HP', 'branch_id': SCOPE})
    assert resp.status_code == 200 and resp.get_json()['ok'] is True
    assert PrintLayout.query.filter_by(name='Purchasing - HP').one()


def test_delete_is_refused_for_staff_and_allowed_for_admin(client, db_session, main_branch):
    _mk('Default', is_default=True)
    doomed = _mk('Doomed')
    _login(client, _user(db_session, main_branch, 'staff1', 'staff'), main_branch)
    assert client.post('/purchase-orders/print-layout/delete',
                       json={'layout_id': doomed.id}).status_code == 403
    _login(client, _user(db_session, main_branch, 'admin1', 'admin'), main_branch)
    assert client.post('/purchase-orders/print-layout/delete',
                       json={'layout_id': doomed.id}).status_code == 200


def test_the_selection_survives_logout(client, db_session, main_branch):
    """AC 3."""
    _mk('Default', is_default=True)
    other = _mk('Other', marker='other')
    user = _user(db_session, main_branch, 'p1', 'staff')
    client.set_cookie(DEVICE_COOKIE, 'workstation-A')
    _login(client, user, main_branch)
    client.post('/purchase-orders/print-layout/select',
                json={'layout_id': other.id, 'branch_id': SCOPE})
    client.get('/logout')
    _login(client, user, main_branch)
    pref = PrintLayoutDevicePref.query.filter_by(device_id='workstation-A').one()
    assert pref.layout_id == other.id


def test_the_selection_belongs_to_the_desk_not_the_person(client, db_session, main_branch):
    """AC 2, as redefined by the per-workstation decision: a DIFFERENT user at the same
    workstation inherits its layout, and the same user at a different workstation does
    not carry it with them."""
    _mk('Default', is_default=True)
    other = _mk('Other', marker='other')
    angilyn = _user(db_session, main_branch, 'angilyn', 'staff')
    newhire = _user(db_session, main_branch, 'newhire', 'staff')

    client.set_cookie(DEVICE_COOKIE, 'workstation-A')
    _login(client, angilyn, main_branch)
    client.post('/purchase-orders/print-layout/select',
                json={'layout_id': other.id, 'branch_id': SCOPE})

    _login(client, newhire, main_branch)          # same desk, different person
    assert resolve_layout('purchase_orders', SCOPE, 'workstation-A').id == other.id

    # same person, different desk -> the default, NOT what she picked at desk A
    assert resolve_layout('purchase_orders', SCOPE, 'workstation-B').name == 'Default'


def test_every_write_is_audited_with_a_real_diff(client, db_session, main_branch):
    _mk('Default', is_default=True)
    row = _mk('Rename me')
    _login(client, _user(db_session, main_branch, 'acct2', 'accountant'), main_branch)
    client.post('/purchase-orders/print-layout/rename',
                json={'layout_id': row.id, 'name': 'Renamed'})
    entry = (AuditLog.query.filter_by(module='purchase_orders',
                                      record_identifier='po_print_layout')
             .order_by(AuditLog.id.desc()).first())
    assert entry is not None
    assert entry.old_values and entry.old_values != '{}', 'audit logged an empty before-state'
    assert 'Rename me' in str(entry.old_values)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_print_layout_routes.py -q`
Expected: FAIL — 404 on every new route.

- [ ] **Step 3: Implement the routes**

Follow `save_cdv_print_layout` in `app/cash_disbursements/views.py:1448` for shape: `@login_required`, permission check then `abort(403)`, `request.get_json(silent=True) or {}`, return `jsonify(ok=True, ...)`. Delete checks `current_user.can_delete_print_layout`; the other three check `current_user.can_edit_print_layout`; select requires only that the user can reach the print screen.

Audit each with `log_audit(module='purchase_orders', action=..., record_identifier='po_print_layout', old_values=get_changes(...), ...)`.

- [ ] **Step 4: Pass the device id at the print call site**

`app/purchase_orders/views.py:1172` becomes:

```python
            layout=get_layout(po.branch_id, device_id=current_device_id()),
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/integration/test_print_layout_routes.py -q` then `python -m pytest -m purchase_orders -q`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add app/purchase_orders/views.py tests/integration/test_print_layout_routes.py
git commit -m "feat(print-layouts): PO routes for save-as, rename, delete, select"
```

---

### Task 7: Designer and print-screen interface

**Files:**
- Modify: `app/purchase_orders/templates/purchase_orders/print_preprinted.html`
- Modify: `app/static/js/po_preprinted_designer.js`
- Test: `tests/integration/test_print_layout_ui.py`, `tests/e2e/test_po_layout_picker.py`

- [ ] **Step 1: Write the failing integration test**

```python
"""The picker as RENDERED. Every absence assertion is scoped to the applied attribute:
the page's inline <style> block names these classes, so a bare `'pp-layout-picker' not
in body` could never fail and would be a test that only looks like one."""
import json
import pytest
from app import db
from app.print_layouts.models import PrintLayout

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _mk(name, is_default=False):
    r = PrintLayout(doc_type='purchase_orders', scope_id=1, name=name,
                    is_default=is_default, payload=json.dumps({}))
    db.session.add(r); db.session.commit()
    return r


def test_the_print_screen_lists_every_layout(client, db_session, main_branch, po_fixture):
    _mk('Default', is_default=True); _mk('Purchasing - HP')
    body = client.get('/purchase-orders/%d/print' % po_fixture.id).data.decode()
    assert 'class="pp-layout-picker"' in body
    assert 'Purchasing - HP' in body


def test_delete_is_absent_from_the_toolbar_for_staff(client, db_session, main_branch,
                                                     po_fixture):
    _mk('Default', is_default=True)
    body = client.get('/purchase-orders/%d/print' % po_fixture.id).data.decode()
    assert 'id="ppDeleteLayoutBtn"' not in body


def test_the_copy_names_printers_not_people(client, db_session, main_branch, po_fixture):
    """Without this line the library fills with per-person duplicates of one printer."""
    _mk('Default', is_default=True)
    body = client.get('/purchase-orders/%d/print' % po_fixture.id).data.decode()
    assert 'Name it after the printer, not the person' in body
```

- [ ] **Step 2: Write the failing e2e test**

Follow `tests/e2e/test_cd_check_designer_digits.py` for the static-harness shape — a stand-in page served over HTTP, driving the real JS file.

```python
def test_picking_in_the_designer_does_not_repoint_the_workstation(designer):
    """Decision 3. An accountant at the Malandag desk fixing the LaserJet layout must
    not silently repoint Malandag at it -- that is the original bug, with a name on it."""
    before = designer.locator('#ppDeviceLayout').inner_text()
    designer.select_option('#ppLayoutPicker', label='Purchasing - HP LaserJet')
    assert designer.locator('#ppDeviceLayout').inner_text() == before


def test_use_on_this_workstation_is_what_repoints_it(designer):
    designer.select_option('#ppLayoutPicker', label='Purchasing - HP LaserJet')
    designer.click('#ppUseHereBtn')
    designer.wait_for_function(
        "() => document.getElementById('ppDeviceLayout').textContent.includes('HP LaserJet')")
```

- [ ] **Step 3: Run both to verify they fail**

Run: `python -m pytest tests/integration/test_print_layout_ui.py -q` and
`python -m pytest tests/e2e/test_po_layout_picker.py -m e2e -q`
Expected: FAIL — no picker in the markup, no `#ppLayoutPicker` in the harness.

- [ ] **Step 4: Implement the toolbar and picker**

Designer toolbar, beside the existing `#editLayoutBtn` (line 80):

```
Editing: [ <select id="ppLayoutPicker"> ]  [Save] [Save as…] [Rename] [Delete]
This workstation uses: <span id="ppDeviceLayout">…</span>  [ Use on this workstation ]
```

The "Save as…" helper text reads: **"Name it after the printer, not the person — e.g. 'Purchasing - LX-310 Malandag'. Layouts are shared, so one name per printer is enough."** Without this the library fills with per-person duplicates of the same printer.

- [ ] **Step 5: Run both to verify they pass**

Run: `python -m pytest tests/integration/test_print_layout_ui.py -q` and `python -m pytest tests/e2e/test_po_layout_picker.py -m e2e -q`
Expected: both PASS.

- [ ] **Step 6: Bump the designer cache-buster**

The template loads `po_preprinted_designer.js?v=N`. Increment N, or browsers serve the old file and the picker silently does nothing.

- [ ] **Step 7: Full suite**

Run: `python -m pytest -q` (~40 min) then `python -m pytest tests/e2e -m e2e -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/purchase_orders/templates app/static/js/po_preprinted_designer.js tests/
git commit -m "feat(print-layouts): layout picker in the PO designer and print screen"
```

---

## Rollout

Deploy is code-first, migration second — the read-through means the new code is inert until rows exist. Follow the `deploy` skill. After the reload and before creating any named layout: **print one PO and compare it on paper against a sheet printed before the migration.** Nothing in this plan substitutes for that.

One release later, remove the dual-write and drop the legacy keys, as a change of its own.
