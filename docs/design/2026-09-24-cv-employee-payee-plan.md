# CV Employee Payee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Cash Disbursement Voucher can name an employee as its payee — settling the employee's posted APVs (Section A) and paying them directly (Section B) — exactly as the AP Voucher already can.

**Architecture:** Mirror the APV's polymorphic payee on `CashDisbursementVoucher`: `payee_type` + `payee_id`, `vendor_id` nullable, `vendor_name`/`vendor_tin` as the snapshot for both kinds. The three payee helpers move from the AP views into `app/common/payee.py` so both vouchers share one rule (employees from any branch the user can *reach*). The form's vendor select becomes a payee select carrying `vendor:<id>` / `employee:<id>`; a new `payee-defaults` endpoint replaces the vendor-only defaults call.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, SQLite (hand-written batch migrations), WTForms, Choices.js, pytest.

**Spec:** `docs/design/2026-09-24-cv-employee-payee-design.md`

## Global Constraints

- Migrations are hand-written batch operations; **no inline `sa.ForeignKey` in a batch `add_column`**; name any FK constraint explicitly. Verify against a **copy of a real database** (`instance/philgen.db`), never a `create_all()` DB.
- Never `datetime.now()` — use `ph_now()` from `app.utils`.
- Never hardcode a GL account code; posting goes through the existing seams (`app/posting/buckets.py`), which this plan does not touch.
- Audit trail: log through `app/audit/utils.py`; build before/after with `model_to_dict`; **verify the audit log in CRUD tests through the real HTTP route**.
- Absence assertions must be scoped (an attribute or element, never a bare class-name substring).
- UI verb: transactions use **"Enter"**, never "New".
- Employee branch rule is **set membership over accessible branches**, never equality with `session['selected_branch_id']`.
- Existing behaviour for vendor payees must not change: the CDV suite (`pytest tests -m cash_disbursements`, 274 tests at the time of writing) stays green after every task.
- Commit after every task. Work on `main` (this repo does not branch per feature); nothing is pushed by this plan.

---

## File map

| File | Responsibility |
|---|---|
| `app/common/payee.py` (create) | `parse_payee`, `accessible_branch_ids`, `employee_payee_query`, `resolve_payee` — one payee rule for APV and CDV |
| `app/accounts_payable/views.py` (modify :295-352, :834, :854-857, :1206, :1229-1232) | delete the three local helpers; import from `app.common.payee` |
| `app/cash_disbursements/models.py` (modify :28-31, :119-123) | `payee_type`, `payee_id`, nullable `vendor_id`, `payee`, `payee_display_name` |
| `migrations/versions/cdvpay_0001_cdv_polymorphic_payee.py` (create) | columns + backfill; downgrade refuses over employee rows |
| `tools/verify_cdvpay_migration.py` (create) | rehearse the migration on a copy of a real DB |
| `app/cash_disbursements/forms.py` (modify :22-24) | `vendor_id` → `payee` StringField |
| `app/cash_disbursements/views.py` (modify: `open_bills` :268-292, `_parse_and_attach_ap_lines` :836-856, `_form_context` :876-910, `create` :1000-1090, `edit` :1133-1250, `_build_check_values` :1608-1612, `list_cdvs` :206-258, `_cdv_export_data` :1702-1741) | payee-aware create/edit/list/export; `payee_defaults` route |
| `app/cash_disbursements/templates/cash_disbursements/form.html` (modify :159-195, :372-392, :508-560) | payee select; JS fetches `payee-defaults` and `open_bills?payee=` |
| `app/cash_disbursements/templates/cash_disbursements/list.html` (modify :91-95) | payee filter |
| `tests/unit/test_common_payee.py` (create) | helper unit tests |
| `tests/integration/test_cdv_employee_payee.py` (create) | picker, Section A, Section B, defaults, check, printouts, audit |
| `tests/integration/test_cdv_payee_migration.py` (create) | migration rehearsal on a fresh migrated DB |

---

### Task 1: One payee rule in `app/common/payee.py`

**Files:**
- Create: `app/common/payee.py`
- Modify: `app/accounts_payable/views.py:295-352` (delete helpers), `:834`, `:854-857`, `:1206`, `:1229-1232` (call the shared ones)
- Test: `tests/unit/test_common_payee.py`

**Interfaces:**
- Produces:
  - `parse_payee(raw: str | None) -> tuple[str | None, int | None]` — `'vendor:12'` → `('vendor', 12)`; anything else → `(None, None)`.
  - `accessible_branch_ids() -> set[int]` — branches `current_user` may act in (all active for full-access users).
  - `employee_payee_query()` — SQLAlchemy query of active `Employee` rows whose `branch_id` is in `accessible_branch_ids()`, ordered by `employee_no`.
  - `resolve_payee(payee_type, payee_id) -> Vendor | Employee | None` — `None` for an unknown id, an unknown type, or an employee in an unreachable branch.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_common_payee.py
"""One payee rule for the APV and the CDV (app/common/payee.py).

Moved out of app/accounts_payable/views.py on 2026-09-24 so the Cash
Disbursement Voucher shares it. Behaviour is the APV's, unchanged:
BUG-AP-EMPLOYEE-PAYEE-PICKER-NOT-BRANCH-FILTERED.
"""
import pytest

from app.common.payee import parse_payee, employee_payee_query, resolve_payee

pytestmark = pytest.mark.unit


@pytest.mark.parametrize('raw, expected', [
    ('vendor:12', ('vendor', 12)),
    ('employee:3', ('employee', 3)),
    ('customer:1', (None, None)),
    ('vendor:', (None, None)),
    ('vendor:abc', (None, None)),
    ('', (None, None)),
    (None, (None, None)),
])
def test_parse_payee(raw, expected):
    assert parse_payee(raw) == expected


def _employee(db_session, branch, no):
    from app.employees.models import Employee
    e = Employee(employee_no=no, first_name='First', last_name=no, branch_id=branch.id,
                 is_active=True)
    db_session.add(e); db_session.commit()
    return e


def _as(client_app, user, branch):
    """Push a request context with `user` logged in and `branch` selected."""
    from flask_login import login_user
    ctx = client_app.test_request_context('/')
    ctx.push()
    login_user(user)
    from flask import session
    session['selected_branch_id'] = branch.id
    return ctx


def test_full_access_user_sees_employees_of_every_branch(app, db_session, admin_user,
                                                         main_branch, branch_manila):
    own = _employee(db_session, main_branch, 'E-OWN')
    other = _employee(db_session, branch_manila, 'E-OTHER')
    ctx = _as(app, admin_user, main_branch)
    try:
        ids = {e.id for e in employee_payee_query().all()}
        assert ids == {own.id, other.id}
        assert resolve_payee('employee', other.id) is other
    finally:
        ctx.pop()


def test_scoped_user_sees_only_reachable_branches(app, db_session, accountant_user,
                                                  main_branch, branch_manila):
    own = _employee(db_session, main_branch, 'E-OWN')
    other = _employee(db_session, branch_manila, 'E-OTHER')
    accountant_user.set_branches([main_branch]); db_session.commit()
    ctx = _as(app, accountant_user, main_branch)
    try:
        assert [e.id for e in employee_payee_query().all()] == [own.id]
        assert resolve_payee('employee', own.id) is own
        assert resolve_payee('employee', other.id) is None, 'unreachable branch must resolve to None'
    finally:
        ctx.pop()


def test_resolve_vendor_and_unknowns(app, db_session, admin_user, main_branch):
    from app.vendors.models import Vendor
    v = Vendor(code='PAYV1', name='Payee Vendor', is_active=True)
    db_session.add(v); db_session.commit()
    ctx = _as(app, admin_user, main_branch)
    try:
        assert resolve_payee('vendor', v.id) is v
        assert resolve_payee('vendor', 999999) is None
        assert resolve_payee('customer', 1) is None
        assert resolve_payee('vendor', None) is None
    finally:
        ctx.pop()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/unit/test_common_payee.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.common.payee'`

- [ ] **Step 3: Create the module** (the bodies are the APV's, verbatim, with the leading underscore dropped)

```python
# app/common/payee.py
"""One payee rule for the vouchers that can pay a vendor OR an employee.

The AP Voucher became polymorphic on 2026-07-08 (payee_type/payee_id, vendor_id
nullable). The Cash Disbursement Voucher followed on 2026-09-24. These helpers
were the APV's private ones and moved here unchanged so both documents apply
the SAME rule -- in particular the employee branch rule:

    an employee from any branch the user can REACH (set membership over
    get_accessible_branches), never equality with the selected branch. A user
    assigned two branches must still pay an employee in the one not selected.
    BUG-AP-EMPLOYEE-PAYEE-PICKER-NOT-BRANCH-FILTERED.

Two layers, both required: employee_payee_query() filters what the picker
OFFERS; resolve_payee() refuses a hand-posted id the picker never showed, by
returning None so the caller's existing "Selected payee not found." path runs
without confirming that the record exists in some other branch.

Vendors are deliberately NOT scoped: they carry no branch_id and are
company-wide, exactly like customers.
"""
from flask_login import current_user

from app import db


def parse_payee(raw):
    """'vendor:12' | 'employee:3' -> (payee_type, payee_id) or (None, None)."""
    try:
        kind, sid = (raw or '').split(':', 1)
        if kind in ('vendor', 'employee'):
            return kind, int(sid)
    except (ValueError, AttributeError):
        pass
    return None, None


def accessible_branch_ids():
    """Branches this user may act in. Full-access users get every active branch."""
    from app.users.utils import get_accessible_branches
    return {b.id for b in get_accessible_branches(current_user)}


def employee_payee_query():
    """Active employees this user may name as a payee, ordered by employee number."""
    from app.employees.models import Employee
    return (Employee.query
            .filter(Employee.is_active.is_(True),
                    Employee.branch_id.in_(accessible_branch_ids()))
            .order_by(Employee.employee_no))


def resolve_payee(payee_type, payee_id):
    """The Vendor/Employee row for the payee, or None (unknown, or unreachable branch)."""
    if not payee_id:
        return None
    if payee_type == 'employee':
        from app.employees.models import Employee
        employee = db.session.get(Employee, payee_id)
        if employee is not None and employee.branch_id not in accessible_branch_ids():
            return None
        return employee
    if payee_type == 'vendor':
        from app.vendors.models import Vendor
        return db.session.get(Vendor, payee_id)
    return None
```

- [ ] **Step 4: Point the APV at the shared module**

In `app/accounts_payable/views.py`: delete `_parse_payee`, `_accessible_branch_ids`, `_employee_payee_query` and `_resolve_payee` (lines 295–352, including their docstrings) and add at the top with the other `app.` imports:

```python
from app.common.payee import (parse_payee as _parse_payee,
                              employee_payee_query as _employee_payee_query,
                              resolve_payee as _resolve_payee)
```

The aliases keep the six call sites (`:834`, `:854`, `:857`, `:1206`, `:1229`, `:1232`) untouched. Check nothing else in the file used `_accessible_branch_ids`: `grep -n "_accessible_branch_ids" app/accounts_payable/views.py` must print nothing.

- [ ] **Step 5: Run the unit tests and the APV payee tests**

Run: `python -m pytest tests/unit/test_common_payee.py tests/integration/test_ap_employee_payee_branch_scope.py tests/integration/test_ap_create_employee_payee.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/common/payee.py app/accounts_payable/views.py tests/unit/test_common_payee.py
git commit -m "refactor(payee): one payee rule for APV and CDV in app/common/payee.py

The three APV helpers (parse, employee picker query, resolve with the
reachable-branch check) move unchanged so the Cash Disbursement Voucher
can share them. Behaviour is identical; the APV imports them under its
old names."
```

---

### Task 2: Model columns and migration `cdvpay_0001`

**Files:**
- Modify: `app/cash_disbursements/models.py:28-31` (columns), `:119-123` (`to_dict`), add two properties
- Create: `migrations/versions/cdvpay_0001_cdv_polymorphic_payee.py`
- Create: `tools/verify_cdvpay_migration.py`
- Test: `tests/integration/test_cdv_payee_migration.py`

**Interfaces:**
- Produces on `CashDisbursementVoucher`: `payee_type: str` (`'vendor'|'employee'`), `payee_id: int`, `vendor_id: int | None`, `payee` (property → `Vendor | Employee | None`), `payee_display_name` (property → `str`).

- [ ] **Step 1: Write the failing model test** (add to a new file)

```python
# tests/integration/test_cdv_payee_migration.py
"""The CDV's polymorphic payee: columns, properties and the migration.

Mirrors the APV's 2026-07-08 change (d9bebfed48f3). Every pre-existing CDV is
a vendor payment, so the backfill sets payee_type='vendor', payee_id=vendor_id
and changes no meaning.
"""
import os
import sqlite3
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def test_model_defaults_to_a_vendor_payee(db_session, main_branch):
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.vendors.models import Vendor
    from app.accounts.models import Account
    v = Vendor(code='MIGV1', name='Mig Vendor', is_active=True)
    cash = Account(code='10190', name='Cash', account_type='Asset', normal_balance='debit', is_active=True)
    db_session.add_all([v, cash]); db_session.commit()
    cdv = CashDisbursementVoucher(branch_id=main_branch.id, cdv_number='MIG-1', cdv_date=date(2026, 9, 24),
                                  vendor_id=v.id, vendor_name=v.name, payee_type='vendor', payee_id=v.id,
                                  payment_method='cash', cash_account_id=cash.id, status='draft',
                                  total_amount=Decimal('1'))
    db_session.add(cdv); db_session.commit()
    assert cdv.payee is v
    assert cdv.payee_display_name == 'Mig Vendor'
    assert cdv.to_dict()['payee_type'] == 'vendor'


def test_an_employee_payee_needs_no_vendor(db_session, main_branch):
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.employees.models import Employee
    from app.accounts.models import Account
    e = Employee(employee_no='E-MIG', first_name='Ana', last_name='Cruz', branch_id=main_branch.id, is_active=True)
    cash = Account(code='10191', name='Cash', account_type='Asset', normal_balance='debit', is_active=True)
    db_session.add_all([e, cash]); db_session.commit()
    cdv = CashDisbursementVoucher(branch_id=main_branch.id, cdv_number='MIG-2', cdv_date=date(2026, 9, 24),
                                  vendor_id=None, vendor_name=e.full_name, payee_type='employee', payee_id=e.id,
                                  payment_method='cash', cash_account_id=cash.id, status='draft',
                                  total_amount=Decimal('1'))
    db_session.add(cdv); db_session.commit()          # vendor_id NULL must be allowed
    assert cdv.payee is e
    assert cdv.payee_display_name == e.full_name
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/integration/test_cdv_payee_migration.py -q`
Expected: FAIL — `TypeError: 'payee_type' is an invalid keyword argument` (first test); the second would fail on `NOT NULL constraint failed: cash_disbursement_vouchers.vendor_id`.

- [ ] **Step 3: Change the model**

In `app/cash_disbursements/models.py` replace lines 28–31:

```python
    # Payee reference (polymorphic: vendor OR employee) -- the APV's shape, since
    # 2026-09-24. vendor_id is set for a vendor payee and NULL for an employee;
    # vendor_name / vendor_tin are the snapshot for EITHER kind (kept under their
    # old names: every template and report reads them).
    payee_type = db.Column(db.String(20), nullable=False, default='vendor',
                           server_default='vendor', index=True)
    payee_id = db.Column(db.Integer, nullable=False, default=0)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True, index=True)
    vendor = db.relationship('Vendor', backref='cash_disbursements')
    vendor_name = db.Column(db.String(200), nullable=False)
    vendor_tin = db.Column(db.String(20))
```

Add after `pays_by_deposit`:

```python
    @property
    def payee(self):
        """Resolve the polymorphic payee to its Vendor or Employee row (or None)."""
        if self.payee_type == 'employee':
            from app.employees.models import Employee
            return db.session.get(Employee, self.payee_id) if self.payee_id else None
        from app.vendors.models import Vendor
        return db.session.get(Vendor, self.payee_id) if self.payee_id else None

    @property
    def payee_display_name(self):
        p = self.payee
        if p is None:
            return self.vendor_name          # historical snapshot fallback
        return p.full_name if self.payee_type == 'employee' else p.name
```

In `to_dict()` add, next to `'vendor_id'`: `'payee_type': self.payee_type, 'payee_id': self.payee_id,`.

- [ ] **Step 4: Write the migration**

```python
# migrations/versions/cdvpay_0001_cdv_polymorphic_payee.py
"""CDV polymorphic payee: vendor OR employee

The Cash Disbursement Voucher takes the AP Voucher's payee shape
(d9bebfed48f3, 2026-07-08): payee_type + payee_id, vendor_id nullable.
Owner, 2026-09-24: employee names were unreachable from a CV -- the CV had
no employee payee at all, so employee APVs could not be paid.

Backfill: every existing CDV is a vendor payment.

Downgrade REFUSES when any employee CDV exists: vendor_id NOT NULL cannot be
restored over rows that legitimately have none. The pre-deploy backup is the
rollback in that case.

Revision ID: cdvpay_0001
Revises: vbank_0001
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'cdvpay_0001'
down_revision = 'vbank_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payee_type', sa.String(length=20), nullable=False,
                                      server_default='vendor'))
        batch_op.add_column(sa.Column('payee_id', sa.Integer(), nullable=False, server_default='0'))
        batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=True)
        batch_op.create_index('ix_cash_disbursement_vouchers_payee_type', ['payee_type'], unique=False)
    op.execute("UPDATE cash_disbursement_vouchers SET payee_type='vendor', payee_id=vendor_id "
               "WHERE payee_id=0 OR payee_id IS NULL")


def downgrade():
    conn = op.get_bind()
    employees = conn.execute(sa.text(
        "SELECT COUNT(*) FROM cash_disbursement_vouchers WHERE payee_type='employee'")).scalar()
    if employees:
        raise RuntimeError(f'{employees} employee-payee CDV(s) exist; vendor_id NOT NULL cannot be '
                           f'restored over them. Restore the pre-deploy backup instead.')
    with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
        batch_op.drop_index('ix_cash_disbursement_vouchers_payee_type')
        batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('payee_id')
        batch_op.drop_column('payee_type')
```

Check the head is what you expect before writing `down_revision`: `flask db heads` must print `vbank_0001 (head)` (set `SECRET_KEY` in the environment if `config.py` refuses to load; the test conftest does the same).

- [ ] **Step 5: Add the migration rehearsal test** (append to `tests/integration/test_cdv_payee_migration.py`)

```python
CAS_ROOT = Path(__file__).resolve().parents[2]


def _run_flask(args, db_path):
    env = dict(os.environ, SECRET_KEY='migration-test', FLASK_APP='flask_app.py',
               SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}', CAS_EXPECT_COMPANY='')
    env.pop('CAS_EXPECT_COMPANY')          # the company guard is for the launcher, not for tests
    return subprocess.run([sys.executable, '-m', 'flask', 'db', *args], cwd=CAS_ROOT, env=env,
                          capture_output=True, text=True, check=True)


def test_upgrade_backfills_every_existing_cdv_as_a_vendor_payment(tmp_path):
    """Real migration history, not create_all(): the pre-cdvpay schema is built by
    upgrading a fresh file to vbank_0001, a vendor CDV is inserted the OLD way, then
    cdvpay_0001 runs."""
    db_path = tmp_path / 'cdvpay.db'; db_path.touch()
    _run_flask(['upgrade', 'vbank_0001'], db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO branches (code, name, is_active) VALUES ('B', 'B', 1)")
    con.execute("INSERT INTO vendors (code, name, is_active) VALUES ('V1', 'Vendor One', 1)")
    con.execute("INSERT INTO accounts (code, name, account_type, normal_balance, is_active) "
                "VALUES ('1010', 'Cash', 'Asset', 'debit', 1)")
    con.execute("INSERT INTO cash_disbursement_vouchers (branch_id, cdv_number, cdv_date, vendor_id, "
                "vendor_name, payment_method, cash_account_id, status, total_amount, created_at, updated_at) "
                "VALUES (1, 'OLD-1', '2026-09-01', 1, 'Vendor One', 'cash', 1, 'posted', 1, "
                "'2026-09-01 00:00:00', '2026-09-01 00:00:00')")
    con.commit(); con.close()

    _run_flask(['upgrade', 'cdvpay_0001'], db_path)

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT payee_type, payee_id, vendor_id FROM cash_disbursement_vouchers").fetchall() \
        == [('vendor', 1, 1)]
    cols = {r[1]: r[3] for r in con.execute("PRAGMA table_info(cash_disbursement_vouchers)")}
    assert cols['vendor_id'] == 0, 'vendor_id must be nullable now'
    assert con.execute("PRAGMA integrity_check").fetchone() == ('ok',)
    con.close()


def test_downgrade_reverses_cleanly_without_employee_rows(tmp_path):
    db_path = tmp_path / 'cdvpay-down.db'; db_path.touch()
    _run_flask(['upgrade', 'cdvpay_0001'], db_path)
    _run_flask(['downgrade', 'vbank_0001'], db_path)
    con = sqlite3.connect(db_path)
    names = {r[1] for r in con.execute("PRAGMA table_info(cash_disbursement_vouchers)")}
    assert 'payee_type' not in names and 'payee_id' not in names
    con.close()


def test_downgrade_refuses_over_an_employee_cdv(tmp_path):
    db_path = tmp_path / 'cdvpay-refuse.db'; db_path.touch()
    _run_flask(['upgrade', 'cdvpay_0001'], db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO branches (code, name, is_active) VALUES ('B', 'B', 1)")
    con.execute("INSERT INTO accounts (code, name, account_type, normal_balance, is_active) "
                "VALUES ('1010', 'Cash', 'Asset', 'debit', 1)")
    con.execute("INSERT INTO cash_disbursement_vouchers (branch_id, cdv_number, cdv_date, vendor_id, "
                "vendor_name, payee_type, payee_id, payment_method, cash_account_id, status, total_amount, "
                "created_at, updated_at) VALUES (1, 'EMP-1', '2026-09-24', NULL, 'Ana Cruz', 'employee', 7, "
                "'cash', 1, 'posted', 1, '2026-09-24 00:00:00', '2026-09-24 00:00:00')")
    con.commit(); con.close()
    with pytest.raises(subprocess.CalledProcessError) as exc:
        _run_flask(['downgrade', 'vbank_0001'], db_path)
    assert 'employee-payee CDV' in exc.value.stderr
```

If the `branches`/`accounts` INSERTs fail on a NOT NULL column you did not list, add that column with a plain value — the intent is a minimal valid row, and `PRAGMA table_info` on the migrated file tells you what is required.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/integration/test_cdv_payee_migration.py -q`
Expected: 5 PASS.

- [ ] **Step 7: Rehearse against a copy of philgen's books**

```python
# tools/verify_cdvpay_migration.py
"""Rehearse cdvpay_0001 on a COPY of a real database. Usage:
    python tools/verify_cdvpay_migration.py instance/philgen.db
Never run against the live file: this copies it to a temp path first."""
import os, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path

src = Path(sys.argv[1]).resolve()
work = Path(tempfile.mkdtemp()) / src.name
shutil.copy(src, work)
env = dict(os.environ, SECRET_KEY='verify', FLASK_APP='flask_app.py',
           SQLALCHEMY_DATABASE_URI=f'sqlite:///{work}')
env.pop('CAS_EXPECT_COMPANY', None)
root = Path(__file__).resolve().parents[1]

def flask(*args):
    return subprocess.run([sys.executable, '-m', 'flask', 'db', *args], cwd=root, env=env,
                          capture_output=True, text=True)

con = sqlite3.connect(work)
before = con.execute("SELECT COUNT(*), SUM(total_amount) FROM cash_disbursement_vouchers").fetchone()
con.close()
r = flask('upgrade', 'cdvpay_0001'); print(r.stdout[-400:], r.stderr[-400:])
con = sqlite3.connect(work)
after = con.execute("SELECT COUNT(*), SUM(total_amount) FROM cash_disbursement_vouchers").fetchone()
bad = con.execute("SELECT COUNT(*) FROM cash_disbursement_vouchers "
                  "WHERE payee_type!='vendor' OR payee_id!=vendor_id").fetchone()[0]
print('rows/total before', before, 'after', after, 'rows not backfilled as vendor:', bad,
      'integrity:', con.execute('PRAGMA integrity_check').fetchone())
con.close()
r = flask('downgrade', 'vbank_0001'); print('downgrade:', r.returncode, r.stderr[-200:])
r = flask('upgrade', 'cdvpay_0001'); print('re-upgrade:', r.returncode)
print('copy at', work)
```

Run: `python tools/verify_cdvpay_migration.py instance/philgen.db`
Expected: same row count and total before/after, `rows not backfilled as vendor: 0`, `integrity: ('ok',)`, downgrade 0, re-upgrade 0.

- [ ] **Step 8: Run the CDV suite and commit**

Run: `python -m pytest tests -m cash_disbursements -q`
Expected: all PASS (the ORM defaults `payee_type='vendor'`, `payee_id=0` on every existing test row).

```bash
git add app/cash_disbursements/models.py migrations/versions/cdvpay_0001_cdv_polymorphic_payee.py tools/verify_cdvpay_migration.py tests/integration/test_cdv_payee_migration.py
git commit -m "feat(cdv): payee_type/payee_id on the CDV; vendor_id nullable (migration cdvpay_0001)

The APV's polymorphic payee shape. Every existing CDV is backfilled as a
vendor payment. Downgrade refuses over employee rows."
```

---

### Task 3: The form takes a payee; create and edit store it

**Files:**
- Modify: `app/cash_disbursements/forms.py:22-24`
- Modify: `app/cash_disbursements/views.py` — `_form_context` (:876-910), `create` (:1000-1090), `edit` (:1133-1250), `_parse_and_attach_ap_lines` (:836-856), `open_bills` (:268-292)
- Modify: `app/cash_disbursements/templates/cash_disbursements/form.html:159-195` (select), `:372-392` and `:508-560` (JS)
- Test: `tests/integration/test_cdv_employee_payee.py`

**Interfaces:**
- Consumes: `parse_payee`, `employee_payee_query`, `resolve_payee` (Task 1); `payee_type`, `payee_id` (Task 2).
- Produces:
  - form field `payee` (`vendor:<id>` / `employee:<id>`); the view also accepts a legacy `vendor_id` POST field and treats it as `vendor:<id>`, so nothing that posts the old field breaks.
  - `GET /cash-disbursements/open-bills?payee=<type:id>` (also accepts `vendor_id=` as before).
  - `_form_context(all_accounts=None, selected_payee=None)` — `selected_payee` is `(payee_type, payee_id)`; template gets `vendors`, `employees`, `current_payee` (`'vendor:12'` string or `''`).

- [ ] **Step 1: Write the failing integration tests**

```python
# tests/integration/test_cdv_employee_payee.py
"""A Cash Disbursement Voucher can pay an EMPLOYEE.

Owner, 2026-09-24: "I cant access the employee names from CV extra. they should
be available for both branches." Not a branch bug: the CV had no employee payee
at all, so the nine employee APVs on production could not be paid by any CV.
Design: docs/design/2026-09-24-cv-employee-payee-design.md.
"""
import json
import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayable
from app.audit.models import AuditLog
from app.cash_disbursements.models import CashDisbursementVoucher
from app.employees.models import Employee
from tests.integration.test_cdv_number_editable import login, setup_accounts, make_vendor

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


@pytest.fixture
def accounts(db_session):
    ap, wt, cash, exp = setup_accounts(db_session)
    return dict(ap=ap, wt=wt, cash=cash, exp=exp)


@pytest.fixture
def employees(db_session, main_branch, branch_manila):
    corp = Employee(employee_no='E-CORP-1', first_name='Anissa', last_name='Tang',
                    tin='111-111-111-000', branch_id=main_branch.id, is_active=True)
    other = Employee(employee_no='E-OTHER-1', first_name='Lawrence', last_name='Kiok',
                     branch_id=branch_manila.id, is_active=True)
    db_session.add_all([corp, other]); db_session.commit()
    return corp, other


def _open(client, branch, username='admin', password='admin123'):
    login(client) if username == 'admin' else client.post(
        '/login', data={'username': username, 'password': password}, follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _employee_apv(db_session, employee, branch, number, total='1000.00'):
    """A POSTED employee-payee APV, the shape the nine on production have."""
    today = date(2026, 9, 24)
    ap = AccountsPayable(ap_number=number, ap_date=today, due_date=today + timedelta(days=30),
                         payee_type='employee', payee_id=employee.id, vendor_id=None,
                         vendor_name=employee.full_name, vendor_tin=employee.tin or '',
                         vendor_address='', branch_id=branch.id, status='posted',
                         subtotal=Decimal(total), vat_amount=Decimal('0'), total_before_wt=Decimal(total),
                         withholding_tax_rate=Decimal('0'), withholding_tax_amount=Decimal('0'),
                         total_amount=Decimal(total), amount_paid=Decimal('0'), balance=Decimal(total),
                         payment_terms='Net 30')
    db_session.add(ap); db_session.commit()
    return ap


def _post_cdv(client, payee, cash, ap_lines=(), expense_lines=(), number='EMP-0001', method='cash'):
    return client.post('/cash-disbursements/create', data={
        'cdv_number': number, 'cdv_date': '2026-09-24', 'payee': payee,
        'payment_method': method, 'cash_account_id': cash.id, 'notes': 'employee payee test',
        'ap_lines': json.dumps(list(ap_lines)), 'expense_lines': json.dumps(list(expense_lines)),
        'vat_override': '0', 'vat_override_value': '0', 'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)


class TestThePicker:

    def test_offers_employees_of_every_reachable_branch(self, client, db_session, admin_user,
                                                        main_branch, branch_manila, employees, accounts):
        """From a session in ONE branch an admin sees BOTH branches' employees --
        'available for both branches'."""
        corp, other = employees
        _open(client, branch_manila)
        html = client.get('/cash-disbursements/create').get_data(as_text=True)
        assert f'value="employee:{corp.id}"' in html
        assert f'value="employee:{other.id}"' in html
        assert '[Employee]' in html and '[Vendor]' in html

    def test_a_scoped_user_does_not_see_an_unreachable_branch(self, client, db_session, admin_user,
                                                              staff_user, main_branch, branch_manila,
                                                              employees, accounts):
        corp, other = employees
        staff_user.set_branches([main_branch]); db_session.commit()
        _open(client, main_branch, 'staff', 'staff123')
        html = client.get('/cash-disbursements/create').get_data(as_text=True)
        assert f'value="employee:{corp.id}"' in html
        assert f'value="employee:{other.id}"' not in html

    def test_a_hand_posted_unreachable_employee_is_refused(self, client, db_session, admin_user,
                                                           staff_user, main_branch, branch_manila,
                                                           employees, accounts):
        corp, other = employees
        staff_user.set_branches([main_branch]); db_session.commit()
        _open(client, main_branch, 'staff', 'staff123')
        resp = _post_cdv(client, f'employee:{other.id}', accounts['cash'],
                         expense_lines=[{'description': 'x', 'amount': 10.0, 'vat_category': '',
                                         'account_id': accounts['exp'].id, 'wt_id': None}])
        assert b'Selected payee not found.' in resp.data
        assert CashDisbursementVoucher.query.filter_by(cdv_number='EMP-0001').first() is None


class TestSectionA:

    def test_open_bills_lists_the_employees_apvs_and_no_vendors(self, client, db_session, admin_user,
                                                                main_branch, employees, accounts):
        corp, _ = employees
        vendor = make_vendor(db_session)
        a1 = _employee_apv(db_session, corp, main_branch, 'E-APV-1')
        a2 = _employee_apv(db_session, corp, main_branch, 'E-APV-2', total='250.00')
        from tests.integration.test_accounts_payable_views import make_ap
        make_ap(db_session, vendor, main_branch, 'V-APV-1')                # a vendor's, must not appear
        _open(client, main_branch)
        bills = client.get(f'/cash-disbursements/open-bills?payee=employee:{corp.id}').get_json()
        assert {b['bill_number'] for b in bills} == {'E-APV-1', 'E-APV-2'}
        assert client.get(f'/cash-disbursements/open-bills?vendor_id={vendor.id}').get_json()[0]['bill_number'] == 'V-APV-1'

    def test_a_cv_settles_an_employee_apv(self, client, db_session, admin_user, main_branch,
                                          employees, accounts):
        corp, _ = employees
        apv = _employee_apv(db_session, corp, main_branch, 'E-APV-3', total='500.00')
        _open(client, main_branch)
        resp = _post_cdv(client, f'employee:{corp.id}', accounts['cash'],
                         ap_lines=[{'bill_id': apv.id, 'amount_applied': 500.0}])
        assert resp.status_code == 200
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='EMP-0001').one()
        assert cdv.payee_type == 'employee' and cdv.payee_id == corp.id
        assert cdv.vendor_id is None and cdv.vendor_name == 'Anissa Tang'
        assert cdv.vendor_tin == '111-111-111-000'
        assert len(cdv.ap_lines) == 1

    def test_the_create_is_audited_with_the_payee(self, client, db_session, admin_user, main_branch,
                                                  employees, accounts):
        corp, _ = employees
        apv = _employee_apv(db_session, corp, main_branch, 'E-APV-4', total='100.00')
        _open(client, main_branch)
        _post_cdv(client, f'employee:{corp.id}', accounts['cash'],
                  ap_lines=[{'bill_id': apv.id, 'amount_applied': 100.0}])
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='EMP-0001').one()
        audit = AuditLog.query.filter_by(module='cash_disbursement', action='create', record_id=cdv.id).first()
        assert audit is not None and '"employee"' in (audit.new_values or '')


class TestVendorPathUnchanged:

    def test_the_legacy_vendor_id_field_still_creates_a_vendor_cv(self, client, db_session,
                                                                  admin_user, main_branch, accounts):
        vendor = make_vendor(db_session)
        _open(client, main_branch)
        resp = client.post('/cash-disbursements/create', data={
            'cdv_number': 'LEG-0001', 'cdv_date': '2026-09-24', 'vendor_id': vendor.id,
            'payment_method': 'cash', 'cash_account_id': accounts['cash'].id, 'notes': 'legacy field',
            'ap_lines': json.dumps([]),
            'expense_lines': json.dumps([{'description': 'Supplies', 'amount': 500.0, 'vat_category': '',
                                          'account_id': accounts['exp'].id, 'wt_id': None}]),
            'vat_override': '0', 'vat_override_value': '0', 'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)
        assert resp.status_code == 200
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='LEG-0001').one()
        assert (cdv.payee_type, cdv.payee_id, cdv.vendor_id) == ('vendor', vendor.id, vendor.id)
```

Check the audit `module` value used by the CDV create route before relying on `'cash_disbursement'`: `grep -n "log_create(" -A2 app/cash_disbursements/views.py`. Use whatever it logs.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/integration/test_cdv_employee_payee.py -q`
Expected: the picker tests FAIL (no `employee:` options), Section A FAIL (`open-bills?payee=` returns `[]`; create says "Selected vendor not found."), the legacy test PASSES already.

- [ ] **Step 3: The form field**

In `app/cash_disbursements/forms.py` replace lines 22–24 with:

```python
    # 'vendor:<id>' | 'employee:<id>' -- the APV's payee shape (2026-09-24).
    # Parsed and resolved in the view (app.common.payee); the picker fills it.
    payee = StringField('Payee', validators=[DataRequired(message='Payee is required.')])
```

Add `StringField` to the `wtforms` import if it is not already there.

- [ ] **Step 4: A payee-from-request helper and `open_bills`**

In `app/cash_disbursements/views.py`, near the imports add `from app.common.payee import parse_payee, employee_payee_query, resolve_payee` and, above `open_bills`, this helper:

```python
def _payee_from_request(form=None):
    """(payee_type, payee_id) from the POSTed `payee`, or from a legacy `vendor_id`
    field (anything that still posts the pre-2026-09-24 name keeps working)."""
    raw = request.form.get('payee') or request.args.get('payee')
    if raw:
        return parse_payee(raw)
    legacy = request.form.get('vendor_id') or request.args.get('vendor_id')
    if legacy:
        return parse_payee(f'vendor:{legacy}')
    return None, None
```

Rewrite the start of `open_bills` (:268-280):

```python
    """Return JSON list of open APV bills for the given PAYEE in the current branch.
    ?payee=vendor:12 | employee:3 (also ?vendor_id=12, the pre-2026-09-24 form)."""
    payee_type, payee_id = _payee_from_request()
    if not payee_id:
        return jsonify([])
    branch_id = session.get('selected_branch_id')
    bills = AccountsPayable.query.filter(
        AccountsPayable.branch_id == branch_id,
        AccountsPayable.payee_type == payee_type,
        AccountsPayable.payee_id == payee_id,
        AccountsPayable.status.in_(['posted', 'partially_paid']),
        AccountsPayable.balance > 0
    ).order_by(AccountsPayable.ap_date).all()
```

- [ ] **Step 5: `_parse_and_attach_ap_lines` scopes bills by payee**

Replace the `AccountsPayable.query.filter_by(id=bill_id, branch_id=cdv.branch_id, vendor_id=cdv.vendor_id)` at `:852-854` with:

```python
        bill = AccountsPayable.query.filter_by(
            id=bill_id, branch_id=cdv.branch_id,
            payee_type=cdv.payee_type, payee_id=cdv.payee_id
        ).first()
        if not bill:
            raise CDVLineError('A selected bill is not available for this payee and branch.')
```

and update the docstring line "Requires cdv.branch_id and cdv.vendor_id" to "cdv.branch_id, cdv.payee_type and cdv.payee_id".

- [ ] **Step 6: `_form_context` offers both kinds**

Change the signature to `def _form_context(all_accounts=None, selected_payee=None):` and the body:

```python
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()
    employees = employee_payee_query().all()
    ...
    # WHT codes seeded for a re-render (edit / failed POST). A vendor gets its
    # assigned codes; an employee gets every active code (design decision 2).
    vendor_whts = []
    if selected_payee and selected_payee[1]:
        payee_type, payee_id = selected_payee
        if payee_type == 'vendor':
            _v = db.session.get(Vendor, payee_id)
            if _v:
                vendor_whts = [w.to_dict() for w in _v.withholding_taxes if w.is_active]
        elif payee_type == 'employee':
            vendor_whts = [w.to_dict() for w in
                           WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()]
    current_payee = f'{selected_payee[0]}:{selected_payee[1]}' if selected_payee and selected_payee[1] else ''
    return dict(vendors=vendors, employees=employees, current_payee=current_payee, all_accounts=all_accounts,
                ...  # the existing keys, unchanged
```

- [ ] **Step 7: `create()`**

Delete the two `form.vendor_id.choices = ...` lines (`:1000-1001`). In `_render_form` pass `selected_payee=_payee_from_request() if is_post else None` instead of `selected_vendor_id=...`. Replace `:1034-1037`:

```python
            payee_type, payee_id = _payee_from_request(form)
            payee = resolve_payee(payee_type, payee_id)
            if not payee:
                flash('Selected payee not found.', 'error')
                return _render_form()
            is_vendor = payee_type == 'vendor'
```

and in the constructor (`:1043-1045`):

```python
                payee_type=payee_type,
                payee_id=payee_id,
                vendor_id=(payee.id if is_vendor else None),
                vendor_name=(payee.name if is_vendor else payee.full_name),
                vendor_tin=payee.tin,
```

In the `log_create(... new_values=model_to_dict(cdv, [...]))` field list add `'payee_type', 'payee_id'` before `'vendor_name'`.

- [ ] **Step 8: `edit()`**

Same four changes: drop the choices lines (`:1133-1134`); `_render_edit_form` passes `selected_payee=(_payee_from_request() if request.method == 'POST' else (cdv.payee_type, cdv.payee_id))`; replace `:1180-1183` with the same resolve block as Step 7; replace `:1196-1198` with:

```python
            cdv.payee_type = payee_type
            cdv.payee_id = payee_id
            cdv.vendor_id = payee.id if is_vendor else None
            cdv.vendor_name = payee.name if is_vendor else payee.full_name
            cdv.vendor_tin = payee.tin
```

Add `'payee_type', 'payee_id'` to both `model_to_dict` field lists around the `log_update`. `grep -n "form.vendor_id" app/cash_disbursements/views.py` must now print nothing.

- [ ] **Step 9: The template select and JS**

Replace `form.html:161-174` with:

```html
          <div id="vendorCard" class="vendor-step-card{% if cdv %} vendor-step-card--done{% endif %}">
            <div class="vendor-step-label" id="vendorCardLabel">
              {% if cdv %}✓ {{ cdv.vendor_name }}{% else %}Step 1 — Select Payee{% endif %}
            </div>
            <select name="payee" id="payee" class="form-control" required
                    {% if not cdv %}autofocus{% endif %}>
              <option value="">Search or select a payee…</option>
              {% for v in vendors %}
              <option value="vendor:{{ v.id }}"
                {% if current_payee == 'vendor:' ~ v.id %}selected{% endif %}>{{ v.code }} : {{ v.name }} [Vendor]</option>
              {% endfor %}
              {% for e in employees %}
              <option value="employee:{{ e.id }}"
                {% if current_payee == 'employee:' ~ e.id %}selected{% endif %}>{{ e.employee_no }} : {{ e.full_name }} [Employee]</option>
              {% endfor %}
            </select>
            {% if form.payee.errors %}<div class="form-error">{{ form.payee.errors[0] }}</div>{% endif %}
          </div>
```

Change the two placeholder texts at `:191` and `:194` from "vendor" to "payee". In the JS (`:388-392`):

```js
const vendorSel = document.getElementById('payee');
vendorSel.addEventListener('change', () => onVendorChange(vendorSel.value));
// Quick-add inserts 'vendor:<id>' so the new vendor's option matches the payee shape.
initVendorQuickAdd({ selectEl: vendorSel, valuePrefix: 'vendor:' });
```

In `onVendorChange` (`:517`) change `document.getElementById('vendor_id')` to `document.getElementById('payee')`, and the open-bills fetch (`:548`) to `?payee=${encodeURIComponent(vendorId)}`. Leave the `/vendors/${vendorId}/defaults` fetch for Task 4 (it is wrong for an employee but harmless: a 404 lands in the `.catch`).

Edit-page preselect: the old `{% if (cdv and cdv.vendor_id == choice[0]) ... %}` is gone; `current_payee` from `_form_context` covers both create-bounce and edit.

- [ ] **Step 10: Run the new tests and the CDV suite**

Run: `python -m pytest tests/integration/test_cdv_employee_payee.py -q` — Expected: all PASS.
Run: `python -m pytest tests -m cash_disbursements -q` — Expected: all PASS. Any test that posts `vendor_id` still passes through the legacy path; a test that asserts on the literal text "Selected vendor not found." must be updated to "Selected payee not found." (`grep -rn "Selected vendor not found" tests`).

- [ ] **Step 11: Commit**

```bash
git add app/cash_disbursements/forms.py app/cash_disbursements/views.py app/cash_disbursements/templates/cash_disbursements/form.html tests/integration/test_cdv_employee_payee.py
git commit -m "feat(cdv): the CV picks a vendor OR an employee as payee

One searchable picker tagged [Vendor]/[Employee], employees from every
branch the user can reach (the APV's rule, now shared). Section A lists
and validates the payee's APVs by payee_type/payee_id. A legacy vendor_id
POST still creates a vendor CV."
```

---

### Task 4: `payee-defaults` endpoint; Section B tax for an employee

**Files:**
- Modify: `app/cash_disbursements/views.py` (new route next to `next_check`)
- Modify: `app/cash_disbursements/templates/cash_disbursements/form.html:535-546` (the defaults fetch)
- Test: `tests/integration/test_cdv_employee_payee.py` (append)

**Interfaces:**
- Produces: `GET /cash-disbursements/payee-defaults?payee=<type:id>` → `{"withholding_taxes": [{id, code, name, rate}], "last_cash_account_id": int|null, "last_expense_account_id": int|null}`. Vendor: identical payload to `/vendors/<id>/defaults`. Employee: every active WHT code; the "last" values from the employee's most recent posted CDV.

- [ ] **Step 1: Write the failing tests** (append to `test_cdv_employee_payee.py`)

```python
class TestSectionB:

    def test_payee_defaults_for_an_employee_offers_every_active_wht_code(self, client, db_session,
                                                                        admin_user, main_branch,
                                                                        employees, accounts):
        from app.withholding_tax.models import WithholdingTax
        for code, rate in (('WC010', '1.00'), ('WC020', '2.00')):
            db_session.add(WithholdingTax(code=code, name=code, rate=Decimal(rate), is_active=True))
        db_session.add(WithholdingTax(code='WC-OFF', name='off', rate=Decimal('5'), is_active=False))
        db_session.commit()
        corp, _ = employees
        _open(client, main_branch)
        d = client.get(f'/cash-disbursements/payee-defaults?payee=employee:{corp.id}').get_json()
        assert [w['code'] for w in d['withholding_taxes']] == ['WC010', 'WC020']
        assert d['last_cash_account_id'] is None and d['last_expense_account_id'] is None

    def test_payee_defaults_for_a_vendor_is_its_assigned_subset(self, client, db_session, admin_user,
                                                                main_branch, accounts):
        """CONTROL: the vendor payload is what /vendors/<id>/defaults gives today."""
        from app.withholding_tax.models import WithholdingTax
        w1 = WithholdingTax(code='WC010', name='a', rate=Decimal('1'), is_active=True)
        w2 = WithholdingTax(code='WC020', name='b', rate=Decimal('2'), is_active=True)
        db_session.add_all([w1, w2]); db_session.commit()
        vendor = make_vendor(db_session); vendor.withholding_taxes.append(w1); db_session.commit()
        _open(client, main_branch)
        d = client.get(f'/cash-disbursements/payee-defaults?payee=vendor:{vendor.id}').get_json()
        assert [w['code'] for w in d['withholding_taxes']] == ['WC010']

    def test_an_employee_expense_cv_with_vat_and_wht_posts(self, client, db_session, admin_user,
                                                           main_branch, employees, accounts):
        from app.withholding_tax.models import WithholdingTax
        from app.vat_categories.models import VATCategory
        wt = WithholdingTax(code='WC010', name='a', rate=Decimal('1'), is_active=True)
        db_session.add(wt)
        if not VATCategory.query.filter_by(code='V12DG').first():
            from tests.integration.test_vendor_views import make_vat_category
            make_vat_category(db_session)
        db_session.commit()
        corp, _ = employees
        _open(client, main_branch)
        resp = _post_cdv(client, f'employee:{corp.id}', accounts['cash'], number='EMP-0002',
                         expense_lines=[{'description': 'Liquidated supplies', 'amount': 1120.0,
                                         'vat_category': 'V12DG', 'account_id': accounts['exp'].id,
                                         'wt_id': wt.id}])
        assert resp.status_code == 200
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='EMP-0002').one()
        assert cdv.payee_type == 'employee'
        assert cdv.expense_lines[0].wt_id == wt.id
        assert cdv.expense_lines[0].vat_amount > 0

    def test_the_form_calls_payee_defaults_not_vendor_defaults(self, client, db_session, admin_user,
                                                               main_branch, accounts):
        _open(client, main_branch)
        html = client.get('/cash-disbursements/create').get_data(as_text=True)
        assert '/cash-disbursements/payee-defaults' in html
        assert re.search(r'/vendors/\$\{[a-zA-Z]+\}/defaults', html) is None
```

If `WithholdingTax` needs other NOT NULL fields, look at `tests/integration/test_vendor_views.py` for how it builds one and copy that.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/integration/test_cdv_employee_payee.py -k SectionB -q`
Expected: FAIL — 404 on `payee-defaults`; the form test fails on the old fetch string.

- [ ] **Step 3: The route** (add below `next_check` in `app/cash_disbursements/views.py`)

```python
@cash_disbursements_bp.route('/cash-disbursements/payee-defaults')
@login_required
def payee_defaults():
    """JSON for the CV form when the payee changes: WHT codes to offer on Section B
    lines, and the cash/bank + expense accounts the payee used last.

    Vendor: exactly what /vendors/<id>/defaults returned (assigned codes; last
    posted CDV's accounts). Employee: EVERY active WHT code -- an employee has no
    assigned subset, and the owner chose 'both VAT and WHT, like a vendor'
    (design decision 2, 2026-09-24) -- plus the same 'last' lookups by payee.
    """
    payee_type, payee_id = _payee_from_request()
    payee = resolve_payee(payee_type, payee_id)
    if payee is None:
        return jsonify({'withholding_taxes': [], 'last_cash_account_id': None,
                        'last_expense_account_id': None})
    if payee_type == 'vendor':
        whts = [w for w in payee.withholding_taxes if w.is_active]
    else:
        whts = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()
    last_cdv = (CashDisbursementVoucher.query
                .filter_by(payee_type=payee_type, payee_id=payee_id, status='posted')
                .order_by(CashDisbursementVoucher.cdv_date.desc(), CashDisbursementVoucher.id.desc())
                .first())
    last_exp = (CDVExpenseLine.query.join(CashDisbursementVoucher)
                .filter(CashDisbursementVoucher.payee_type == payee_type,
                        CashDisbursementVoucher.payee_id == payee_id,
                        CashDisbursementVoucher.status == 'posted',
                        CDVExpenseLine.account_id.isnot(None))
                .order_by(CashDisbursementVoucher.cdv_date.desc(), CashDisbursementVoucher.id.desc(),
                          CDVExpenseLine.line_number.asc())
                .first())
    return jsonify({
        'withholding_taxes': [{'id': w.id, 'code': w.code, 'name': w.name, 'rate': float(w.rate)}
                              for w in whts],
        'last_cash_account_id': last_cdv.cash_account_id if last_cdv else None,
        'last_expense_account_id': last_exp.account_id if last_exp else None,
    })
```

`WithholdingTax` is already imported at the top of the file (`:16`); `CDVExpenseLine` at `:8`.

- [ ] **Step 4: The form fetch** — in `form.html` change `fetch(\`/vendors/${vendorId}/defaults\`)` to `fetch(\`/cash-disbursements/payee-defaults?payee=${encodeURIComponent(vendorId)}\`)` and the comment above it from "vendor's withholding codes" to "payee's withholding codes (a vendor's assigned ones; every active code for an employee)".

- [ ] **Step 5: Run and commit**

Run: `python -m pytest tests/integration/test_cdv_employee_payee.py tests/integration/test_cdv_views.py -q` — Expected: PASS.

```bash
git add app/cash_disbursements/views.py app/cash_disbursements/templates/cash_disbursements/form.html tests/integration/test_cdv_employee_payee.py
git commit -m "feat(cdv): payee-defaults serves WHT codes and last accounts for either payee kind

An employee line offers every active WHT code (owner: both VAT and WHT,
like a vendor); a vendor keeps its assigned subset."
```

---

### Task 5: Check, printouts, detail, list filter, export

**Files:**
- Modify: `app/cash_disbursements/views.py` — `_build_check_values` (:1608-1612), `list_cdvs` (:206-210, :249-258), `_cdv_export_data` (:1702-1711, :1741)
- Modify: `app/cash_disbursements/templates/cash_disbursements/list.html:91-95`
- Test: `tests/integration/test_cdv_employee_payee.py` (append)

**Interfaces:**
- Consumes: `cdv.payee_type`, `cdv.vendor` (None for an employee), `employee_payee_query`.
- Produces: list/export filter param `payee=<type:id>` (legacy `vendor=<id>` still accepted); export column `Payee Type`.

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestPrintoutsAndLists:

    def _employee_check_cv(self, client, db_session, main_branch, employees, accounts):
        corp, _ = employees
        apv = _employee_apv(db_session, corp, main_branch, 'E-APV-9', total='300.00')
        _open(client, main_branch)
        _post_cdv(client, f'employee:{corp.id}', accounts['cash'], number='EMP-CHK',
                  method='check', ap_lines=[{'bill_id': apv.id, 'amount_applied': 300.0}])
        cdv = CashDisbursementVoucher.query.filter_by(cdv_number='EMP-CHK').one()
        cdv.check_number = 'CHK-9001'; cdv.status = 'posted'; db_session.commit()
        return cdv

    def test_the_check_names_the_employee(self, client, db_session, admin_user, main_branch,
                                          employees, accounts):
        cdv = self._employee_check_cv(client, db_session, main_branch, employees, accounts)
        html = client.get(f'/cash-disbursements/{cdv.id}/print-check').get_data(as_text=True)
        m = re.search(r'data-el="payee"[^>]*>([^<]*)</div>', html)
        assert m and m.group(1) == 'Anissa Tang'

    def test_detail_and_print_show_the_employee_and_no_deposit_block(self, client, db_session,
                                                                     admin_user, main_branch,
                                                                     employees, accounts):
        cdv = self._employee_check_cv(client, db_session, main_branch, employees, accounts)
        cdv.payment_method = 'bank_transfer'; db_session.commit()
        for url in (f'/cash-disbursements/{cdv.id}', f'/cash-disbursements/{cdv.id}/print'):
            html = client.get(url).get_data(as_text=True)
            assert 'Anissa Tang' in html
            assert 'data-deposit-to' not in html, url

    def test_the_list_filters_by_employee(self, client, db_session, admin_user, main_branch,
                                          employees, accounts):
        corp, _ = employees
        cdv = self._employee_check_cv(client, db_session, main_branch, employees, accounts)
        html = client.get(f'/cash-disbursements?payee=employee:{corp.id}').get_data(as_text=True)
        assert 'EMP-CHK' in html
        assert f'<option value="employee:{corp.id}"' in html

    def test_the_export_carries_the_payee_type(self, client, db_session, admin_user, main_branch,
                                               employees, accounts):
        self._employee_check_cv(client, db_session, main_branch, employees, accounts)
        from app.cash_disbursements.views import _cdv_export_data
        with client.application.test_request_context('/cash-disbursements/export/csv'):
            from flask import session as s; s['selected_branch_id'] = main_branch.id
            rows, columns, headers = _cdv_export_data(main_branch.id)
        assert 'Payee Type' in headers
        assert any(r['Payee Type'] == 'employee' for r in rows)
```

Check `_cdv_export_data`'s real return shape (`grep -n "return" app/cash_disbursements/views.py | sed -n '/1740/,/1760/p'`) and adjust the unpacking if it differs; the assertion on `'Payee Type'` is the point.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/integration/test_cdv_employee_payee.py -k Printouts -q`
Expected: check test PASSES already (falls back to `vendor_name`); detail/print PASS already (`cdv.vendor` is None → no block); list and export FAIL.

- [ ] **Step 3: `_build_check_values`** — make the intent explicit (behaviour is already right):

```python
    # Who the cheque is made out to. A VENDOR may carry a Check Payee Name alias
    # (2026-09-23); an EMPLOYEE has none, so the snapshot -- the full name -- is
    # the payee. Read live from the vendor, no snapshot (owner ruling 2026-09-06).
    alias = ''
    if cdv.payee_type == 'vendor' and cdv.vendor:
        alias = (cdv.vendor.check_payee_name or '').strip()
    payee = alias or cdv.vendor_name
```

- [ ] **Step 4: List filter and export**

In `list_cdvs` replace `:206-210`:

```python
    payee_filter = request.args.get('payee') or (
        f"vendor:{request.args.get('vendor')}" if request.args.get('vendor', 'all') != 'all' else 'all')
    if payee_filter != 'all':
        p_type, p_id = parse_payee(payee_filter)
        if p_id:
            query = query.filter_by(payee_type=p_type, payee_id=p_id)
```

and pass `employees=employee_payee_query().all(), payee_filter=payee_filter` to the template alongside `vendors` (keep `vendor_filter=payee_filter` too if the template's `filters_active` line still reads it — or update that line to `payee_filter`). In `list.html:91-95`:

```html
    <select name="payee" id="vendor-filter" class="form-control form-control-sm">
        <option value="all">All Payees</option>
        {% for v in vendors %}
        <option value="vendor:{{ v.id }}" {% if payee_filter == 'vendor:' ~ v.id %}selected{% endif %}>{{ v.name }} [Vendor]</option>
        {% endfor %}
        {% for e in employees %}
        <option value="employee:{{ e.id }}" {% if payee_filter == 'employee:' ~ e.id %}selected{% endif %}>{{ e.full_name }} [Employee]</option>
        {% endfor %}
    </select>
```

In `_cdv_export_data` apply the same filter parsing in place of `:1702-1711`, and add `'Payee Type': cdv.payee_type` next to `'Vendor': cdv.vendor_name` (`:1741`), with `'Payee Type'` appended to the `columns` list (the function returns `data, columns, columns` -- headers are the columns).

- [ ] **Step 5: Run, then the whole module, then commit**

Run: `python -m pytest tests/integration/test_cdv_employee_payee.py -q` — PASS.
Run: `python -m pytest tests -m cash_disbursements -q` — PASS.

```bash
git add app/cash_disbursements/views.py app/cash_disbursements/templates/cash_disbursements/list.html tests/integration/test_cdv_employee_payee.py
git commit -m "feat(cdv): check, printouts, list filter and export know an employee payee"
```

---

### Task 6: Whole-suite check, docs, deploy note

**Files:**
- Modify: `docs/PROJECT_STATUS.md` (Cash Disbursements entry — one line: "payee is vendor or employee, 2026-09-24")
- Modify: `docs/design/2026-09-24-cv-employee-payee-design.md` (Status line → "implemented <commit>")

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q -p no:cacheprovider` (≈35 min)
Expected: 0 failed, 0 errors. Anything red is yours to fix before the next step — the likeliest candidates are tests that read the CDV form for `name="vendor_id"` (now `name="payee"`) or the text "Select Vendor" (now "Select Payee"); update the assertion, not the behaviour.

- [ ] **Step 2: Rehearse the migration once more on a fresh copy**

Run: `python tools/verify_cdvpay_migration.py instance/philgen.db`
Expected: as in Task 2 Step 7.

- [ ] **Step 3: Docs and commit**

```bash
git add docs/PROJECT_STATUS.md docs/design/2026-09-24-cv-employee-payee-design.md
git commit -m "docs(cdv): employee payee implemented"
```

- [ ] **Step 4: Hand off for deploy**

Not part of this plan: the `deploy` skill. Tell the owner the deploy needs `flask db upgrade` → `cdvpay_0001` and that the nine employee APVs become payable the moment the reload takes; verify live by opening a CV form in EXTRA and finding a CORP employee in the payee picker.
