# Purchase Order Found After Submit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a receiver be warned when a no-PO line probably belongs to an open purchase order, and let a submitted receipt be sent back to draft so the link can be corrected.

**Architecture:** Two independent halves sharing one migration. *Prevention* is client-side: `_po_lines_payload` gains `product_id`, which reaches the `/receiving-reports/open-lines` endpoint the form already calls, so opening "Add Item Without PO" can fetch the vendor's open lines and warn when the chosen product matches one; an override stores a reason on the line. *Repair* mirrors the purchase-requisition `return_to_draft` route already in this codebase — memo required, audit-logged, cleared on re-submit — after which the ordinary edit form does the work.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, SQLite, Alembic (hand-written migrations), Jinja2, vanilla JS, pytest.

**Spec:** `docs/design/2026-09-07-rr-po-found-after-submit-design.md`

## Global Constraints

- **Never use a naive `datetime.now()`.** Use `ph_now()` from `app.utils` (Philippine Standard Time, UTC+8). Naive timestamps corrupt period boundaries and audit ordering.
- **Migrations are hand-written.** `Migrate()` is configured without `render_as_batch`, so autogenerate emits plain `ALTER`s SQLite cannot run. Use `op.batch_alter_table`.
- **A batch `add_column` cannot carry an inline `sa.ForeignKey`** — the table rebuild raises "Constraint must have a name". Declare a plain `sa.Integer()` in the migration and keep `db.ForeignKey` on the ORM side.
- **Verify every migration against a copy of a real database**, never a `create_all()` test database. Copy `instance/philgen.db`, upgrade it, and confirm foreign keys, indexes, row counts and `PRAGMA integrity_check`.
- **Audit through `app/audit/utils.py`.** Lifecycle events use their own `action=` (not a generic `update`) — the audit log's Actions filter is built from the distinct actions present.
- **A picker filter is not enforcement.** Anything the client offers must be re-validated where the POST lands.
- **EXCEPTION, and it is specified behaviour rather than an oversight: the no-PO warning is ADVISORY.** The override reason is validated where the POST lands (type-checked, capped at 200 characters, stored) but is **not required**, and the server does **not** refuse a direct line that lacks one even when an open order matches. Owner decision, 2026-09-07: this fires on a weekly-or-more event, and a save-time refusal would bounce a receipt the receiver believed finished. The residual gap — a raw POST, or an order approved between picking and saving — is accepted and documented. Task 8's list marker is the compensating control. Do not add a server-side refusal; a change of mind here is a spec change, not a fix.
- **Absence assertions must be scoped.** Inline `<style>`/JS text leaks into the rendered response, so assert on an applied attribute (`class="x y"`), never a bare class name.
- **Test markers must be registered** in `pytest.ini`. `receiving_reports` already is.
- **Run tests through the real HTTP route**, not the service layer alone.
- **Never write `alert(`, `confirm(` or `prompt(` anywhere in a template** — including comments. `tests/integration/test_rr_form_render.py::test_no_javascript_popup_is_used` scans the served HTML.
- **`RR_EDIT_ROLES = ('staff', 'accountant', 'admin', 'chief_accountant')`**; approver means `current_user.has_full_access or current_user.role == 'accountant'`.
- Restart the dev server after any `.py` change — `flask_app.py` runs `use_reloader=False`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `migrations/versions/rrreason_0001_return_to_draft_and_no_po_reason.py` | the four new columns | create |
| `app/receiving_reports/models.py` | ORM columns + `RETURN_TO_DRAFT_STATUSES` | modify |
| `app/receiving_reports/views.py` | return-to-draft route, submit clearing, payload `product_id`, `no_po_reason` parsing | modify |
| `app/receiving_reports/templates/receiving_reports/detail.html` | Return to Draft button, modal, memo display | modify |
| `app/receiving_reports/templates/receiving_reports/form.html` | pick-time warning, reason field, serialiser | modify |
| `app/receiving_reports/templates/receiving_reports/list.html` | direct-line marker | modify |
| `tests/integration/test_rr_return_to_draft.py` | repair half | create |
| `tests/integration/test_rr_no_po_warning.py` | prevention half | create |

Prevention and repair get **separate test files**. They share only the migration; keeping them apart means a failure names which half broke.

---

## Task 1: Schema

**Files:**
- Create: `migrations/versions/rrreason_0001_return_to_draft_and_no_po_reason.py`
- Modify: `app/receiving_reports/models.py`
- Test: `tests/integration/test_rr_return_to_draft.py`

**Interfaces:**
- Consumes: nothing. Migration head is currently `rruom_0001`.
- Produces: `ReceivingReport.return_reason` (str|None), `.returned_by_id` (int|None), `.returned_at` (datetime|None); `ReceivingReportItem.no_po_reason` (str|None); `ReceivingReport.RETURN_TO_DRAFT_STATUSES = ('submitted',)`.

- [ ] **Step 1: Confirm the current migration head**

Run: `flask db heads`
Expected: `rruom_0001 (head)`

If it prints anything else, stop — the `down_revision` below is wrong and the plan needs revisiting.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_rr_return_to_draft.py`:

```python
"""A submitted receiving report can be sent back to draft.

Owner request 2026-09-07, after PO-less receipts shipped: somebody finds the purchase
order that covered the goods AFTER the receipt was submitted. A receiving report is
editable only while `draft` and has no unsubmit, so the link could not be attached at
all -- the only exits were approve or cancel.

Scope is `submitted` only. Approved and billed are out (spec decision): approved has
posted stock and GRNI, and billed cannot even be cancelled today.
"""
from datetime import date

import pytest

from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]

MEMO = 'The goods were on PO-00985 after all.'


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='RTD-V', name='Return Test Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def product(db_session):
    from app.products.models import Product
    p = Product(code='RTD-P', name='Returned Item', track_inventory=False, is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _rr(db_session, branch, vendor, product, user, status='submitted',
        number='RR-RTD-1'):
    rr = ReceivingReport(rr_number=number, receipt_date=date(2026, 9, 7),
                         branch_id=branch.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, status=status,
                         created_by_id=user.id,
                         submitted_by_id=(user.id if status != 'draft' else None))
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=None, product_id=product.id,
        received_quantity=3))
    db_session.add(rr); db_session.commit()
    return rr


class TestTheSchema:

    def test_the_receipt_carries_the_memo_fields(self):
        cols = {c.key for c in ReceivingReport.__table__.columns}
        assert {'return_reason', 'returned_by_id', 'returned_at'} <= cols

    def test_the_line_carries_a_no_po_reason(self):
        cols = {c.key for c in ReceivingReportItem.__table__.columns}
        assert 'no_po_reason' in cols

    def test_every_new_column_is_nullable(self):
        """Nothing to backfill: every existing row reads NULL and behaves as before."""
        for model, names in ((ReceivingReport,
                              ('return_reason', 'returned_by_id', 'returned_at')),
                             (ReceivingReportItem, ('no_po_reason',))):
            for name in names:
                assert model.__table__.c[name].nullable is True, name

    def test_only_submitted_is_returnable(self):
        """A receiving report has no `rejected` status, unlike the requisition, so
        there is exactly one source state."""
        assert ReceivingReport.RETURN_TO_DRAFT_STATUSES == ('submitted',)
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov`
Expected: FAIL — `KeyError: 'return_reason'` / `AttributeError: RETURN_TO_DRAFT_STATUSES`

- [ ] **Step 4: Write the migration**

Create `migrations/versions/rrreason_0001_return_to_draft_and_no_po_reason.py`:

```python
"""return-to-draft memo on a receiving report, and a no-PO override reason on its lines

Two additions from one design (docs/design/2026-09-07-rr-po-found-after-submit-design.md):

  receiving_reports.return_reason / returned_by_id / returned_at
      A submitted receipt can be sent back to draft when the purchase order that
      covered the goods turns up afterwards. The memo says why.

  receiving_report_items.no_po_reason
      A direct line whose product HAS an open order line for the same vendor is
      flagged at entry. If the receiver says it genuinely had no order, that
      judgement is recorded here rather than lost.

All four nullable and additive. Nothing to backfill: every existing row reads NULL and
behaves exactly as it does today.

returned_by_id is a PLAIN INTEGER here with db.ForeignKey on the ORM side only -- a
SQLite batch add_column cannot carry an inline foreign key ("Constraint must have a
name" during the table rebuild). Same arrangement prreturn_0001 used, and the reason
receiving_report_items shows three foreign keys in the live database rather than five.

Revision ID: rrreason_0001
Revises: rruom_0001
Create Date: 2026-09-07

"""
from alembic import op
import sqlalchemy as sa


revision = 'rrreason_0001'
down_revision = 'rruom_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('receiving_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('return_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('returned_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('returned_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('receiving_report_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('no_po_reason', sa.Text(), nullable=True))


def downgrade():
    """Drops the columns and the memos in them.

    Safe: nothing derives from these. A downgraded database loses the record of WHY a
    receipt was returned or why a line was kept without an order, but every receipt and
    line still reads correctly. The audit log keeps both texts regardless.
    """
    with op.batch_alter_table('receiving_report_items', schema=None) as batch_op:
        batch_op.drop_column('no_po_reason')
    with op.batch_alter_table('receiving_reports', schema=None) as batch_op:
        batch_op.drop_column('returned_at')
        batch_op.drop_column('returned_by_id')
        batch_op.drop_column('return_reason')
```

- [ ] **Step 5: Add the ORM columns**

In `app/receiving_reports/models.py`, inside `class ReceivingReport`, immediately after the `submitted_at` column:

```python
    # Sent back to draft because the purchase order that covered these goods turned up
    # after submission (rrreason_0001). CLEARED on re-submit -- a memo describes one
    # correction cycle, and submitting starts the next.
    #
    # returned_by_id keeps db.ForeignKey HERE and not in the migration: a SQLite batch
    # add_column cannot carry an inline FK.
    returned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    returned_at = db.Column(db.DateTime)
    return_reason = db.Column(db.Text)
```

Directly above the `id` column of `class ReceivingReport`, add the tuple:

```python
    #: The one status a receipt can be sent back to draft from. Unlike the purchase
    #: requisition, a receiving report has no `rejected` state, so there is exactly one.
    RETURN_TO_DRAFT_STATUSES = ('submitted',)
```

In `class ReceivingReportItem`, after `unit_of_measure_ref`:

```python
    # Why this line was kept as a direct receipt even though the vendor had an open
    # order line for the same product (rrreason_0001). NULL when no warning fired --
    # a line with nothing to explain should carry no explanation.
    no_po_reason = db.Column(db.Text)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 7: Verify the migration on a copy of the live database**

```bash
S="$TMPDIR/migcheck"; mkdir -p "$S"
cp instance/philgen.db "$S/check.db"
python -c "
import sqlite3
c = sqlite3.connect(r'$S/check.db')
for t in ('receiving_reports', 'receiving_report_items'):
    print(t, 'fks=', len(c.execute('PRAGMA foreign_key_list(%s)' % t).fetchall()),
          'rows=', c.execute('select count(*) from %s' % t).fetchone()[0],
          'idx=', sorted(r[1] for r in c.execute('PRAGMA index_list(%s)' % t)))
"
SQLALCHEMY_DATABASE_URI="sqlite:///$S/check.db" flask db upgrade
python -c "
import sqlite3
c = sqlite3.connect(r'$S/check.db')
for t in ('receiving_reports', 'receiving_report_items'):
    print(t, 'fks=', len(c.execute('PRAGMA foreign_key_list(%s)' % t).fetchall()),
          'rows=', c.execute('select count(*) from %s' % t).fetchone()[0],
          'idx=', sorted(r[1] for r in c.execute('PRAGMA index_list(%s)' % t)))
print('integrity:', c.execute('PRAGMA integrity_check').fetchone()[0])
print('fk check:', c.execute('PRAGMA foreign_key_check').fetchall() or 'clean')
"
```

Expected: foreign-key counts, row counts and index lists **identical before and after**; `integrity: ok`; `fk check: clean`.

If any count changes, stop. The batch rebuild has dropped something and the migration is wrong.

- [ ] **Step 8: Apply it to the development database and restart the server**

```bash
flask db upgrade
flask db current      # expect: rrreason_0001 (head)
```

Then restart the dev server — `use_reloader=False` means Python changes need it.

- [ ] **Step 9: Commit**

```bash
git add migrations/versions/rrreason_0001_return_to_draft_and_no_po_reason.py \
        app/receiving_reports/models.py \
        tests/integration/test_rr_return_to_draft.py
git commit -m "feat(rr): columns for the return-to-draft memo and the no-PO override reason"
```

---

## Task 2: The Return to Draft route

**Files:**
- Modify: `app/receiving_reports/views.py`
- Test: `tests/integration/test_rr_return_to_draft.py`

**Interfaces:**
- Consumes: `ReceivingReport.RETURN_TO_DRAFT_STATUSES`, `.return_reason`, `.returned_by_id`, `.returned_at` from Task 1.
- Produces: route endpoint `receiving_reports.return_to_draft` (POST, `/receiving-reports/<int:id>/return-to-draft`), and `_may_return_to_draft(rr) -> bool`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_rr_return_to_draft.py`:

```python
class TestWhoMayReturnIt:

    def test_an_approver_may(self, client, db_session, main_branch, vendor, product,
                             admin_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'draft'

    def test_the_submitter_may_too(self, client, db_session, main_branch, vendor,
                                   product, staff_user):
        """Owner decision 2026-09-07: pulling back your OWN submission needs nobody
        else's authority."""
        rr = _rr(db_session, main_branch, vendor, product, staff_user)
        _login(client, staff_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'draft'

    def test_an_unrelated_staff_user_may_not(self, client, db_session, main_branch,
                                             vendor, product, admin_user, staff_user):
        """CONTROL. Without this the two tests above pass on a route with no gate."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, staff_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'submitted'

    def test_a_null_submitter_falls_back_to_approver_only(self, client, db_session,
                                                          main_branch, vendor, product,
                                                          admin_user, staff_user):
        """Receipts predating submitted_by_id, or seeded directly, have NULL there.
        `None == user.id` is False, so the rule fails CLOSED rather than opening the
        route to everyone."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        rr.submitted_by_id = None
        db_session.commit()
        _login(client, staff_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'submitted'


class TestWhatItRefuses:

    @pytest.mark.parametrize('status', ['draft', 'approved', 'billed', 'cancelled'])
    def test_only_a_submitted_receipt_can_be_returned(self, client, db_session,
                                                      main_branch, vendor, product,
                                                      admin_user, status):
        rr = _rr(db_session, main_branch, vendor, product, admin_user, status=status,
                 number='RR-RTD-%s' % status)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == status

    def test_a_short_memo_is_refused(self, client, db_session, main_branch, vendor,
                                     product, admin_user):
        """Matching reject/cancel: 10 characters. The memo is the whole value of the
        record afterwards."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        body = client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                           data={'return_reason': 'oops'},
                           follow_redirects=True).data.decode()
        db_session.refresh(rr)
        assert rr.status == 'submitted'
        assert 'min 10' in body


class TestWhatItRecords:

    def test_the_memo_who_and_when_are_stored(self, client, db_session, main_branch,
                                              vendor, product, admin_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.return_reason == MEMO
        assert rr.returned_by_id == admin_user.id
        assert rr.returned_at is not None

    def test_it_is_audit_logged_under_its_own_action(self, client, db_session,
                                                     main_branch, vendor, product,
                                                     admin_user):
        """action='return_to_draft', not a generic 'update': the audit log's Actions
        filter is built from the distinct actions present, so a lifecycle event logged
        as an update is unfilterable and reads as an ordinary edit."""
        from app.audit.models import AuditLog
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        entry = (AuditLog.query
                 .filter_by(module='receiving_reports', action='return_to_draft',
                            record_id=rr.id)
                 .order_by(AuditLog.id.desc()).first())
        assert entry is not None
        assert MEMO in (entry.notes or '')
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov -k "WhoMay or WhatIt"`
Expected: FAIL — 404, because the route does not exist yet.

- [ ] **Step 3: Add the gate helper**

In `app/receiving_reports/views.py`, immediately after `_approve_role_gate()`:

```python
def _may_return_to_draft(rr):
    """Who may send a submitted receipt back to draft.

    An approver, OR the person who submitted it. The approver half matches cancel() on
    this same document -- reversing a submission is the same weight of act. The
    submitter half is an owner decision (2026-09-07): pulling back your own submission
    is not something that needs somebody else's authority.

    Fails CLOSED on a NULL submitted_by_id -- receipts predating that column, or seeded
    directly, compare False and fall back to approver-only.
    """
    if current_user.has_full_access or current_user.role == 'accountant':
        return True
    return rr.submitted_by_id is not None and rr.submitted_by_id == current_user.id
```

- [ ] **Step 4: Add the route**

In `app/receiving_reports/views.py`, immediately after the `submit()` route:

```python
@receiving_reports_bp.route('/receiving-reports/<int:id>/return-to-draft',
                            methods=['POST'])
@login_required
def return_to_draft(id):
    """Send a submitted receipt back to draft so its lines can be corrected.

    The case this exists for: a receipt recorded goods as a DIRECT receipt (no purchase
    order), and the order that covered them turned up afterwards. A receiving report is
    editable only while draft and has no unsubmit, so before this the only exits were
    approve -- committing the mistake -- or cancel, which burns the receipt number and
    means re-keying every line.

    It deliberately does NOT re-point anything. Which order a delivery belongs to is a
    judgement only a person can make; the receiver removes the direct line and pulls the
    real one through the ordinary picker, where the ceiling and vendor/branch/status
    guards already apply.

    A memo is REQUIRED (min 10 chars, matching reject/cancel and the requisition
    equivalent): this reverses a submission, and "why" is the whole value of the record
    afterwards.
    """
    rr = _rr_or_404(id)
    gate = _rr_role_gate()
    if gate:
        return gate
    if not _may_return_to_draft(rr):
        flash('Only an approver or the person who submitted it can return this '
              'Receiving Report to draft.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    if rr.status not in ReceivingReport.RETURN_TO_DRAFT_STATUSES:
        flash('Only a submitted Receiving Report can be returned to draft.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    reason = (request.form.get('return_reason') or '').strip()
    if len(reason) < 10:
        flash('A reason (min 10 chars) is required to return this to draft.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    from_status = rr.status
    rr.status = 'draft'
    rr.returned_by_id = current_user.id
    rr.returned_at = ph_now()
    rr.return_reason = reason
    db.session.commit()
    log_audit(module='receiving_reports', action='return_to_draft', record_id=rr.id,
              record_identifier=rr.rr_number,
              notes=f'Returned to draft from {from_status}: {reason}')
    flash(f'Receiving Report "{rr.rr_number}" returned to draft.', 'success')
    return redirect(url_for('receiving_reports.view', id=id))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov`
Expected: PASS (all)

- [ ] **Step 6: Mutation-check the gate**

Temporarily change `_may_return_to_draft` to `return True`, run
`python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov -k WhoMay`.
Expected: **2 failures** (`test_an_unrelated_staff_user_may_not`, `test_a_null_submitter_falls_back_to_approver_only`). Restore the function, re-run, expect PASS.

A gate with no failing control test cannot tell "correctly closed" from "dead".

- [ ] **Step 7: Commit**

```bash
git add app/receiving_reports/views.py tests/integration/test_rr_return_to_draft.py
git commit -m "feat(rr): send a submitted receiving report back to draft with a memo"
```

---

## Task 3: Clear the memo on re-submit

**Files:**
- Modify: `app/receiving_reports/views.py` (the `submit()` route)
- Test: `tests/integration/test_rr_return_to_draft.py`

**Interfaces:**
- Consumes: the three memo columns from Task 1, the route from Task 2.
- Produces: nothing new; changes `submit()` behaviour.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_rr_return_to_draft.py`:

```python
class TestResubmittingClearsThePreviousCycle:
    """The correction applied to purchase requisitions in fa78173a, applied here.

    A memo describes ONE correction cycle. Carrying it forward leaves a freshly
    submitted receipt still displaying "Returned to draft: ..." -- describing a
    correction that has since been made and acted on.
    """

    def _returned(self, client, db_session, main_branch, vendor, product, user):
        rr = _rr(db_session, main_branch, vendor, product, user)
        _login(client, user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.return_reason == MEMO
        return rr

    def test_the_memo_and_its_provenance_are_cleared(self, client, db_session,
                                                     main_branch, vendor, product,
                                                     admin_user):
        rr = self._returned(client, db_session, main_branch, vendor, product, admin_user)
        client.post('/receiving-reports/%s/submit' % rr.id, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'submitted'
        assert rr.return_reason is None
        assert rr.returned_by_id is None
        assert rr.returned_at is None

    def test_the_history_survives_in_the_audit_log(self, client, db_session, main_branch,
                                                   vendor, product, admin_user):
        """What makes clearing safe rather than destructive. If this stops holding, the
        clear becomes the deletion of the only copy."""
        from app.audit.models import AuditLog
        rr = self._returned(client, db_session, main_branch, vendor, product, admin_user)
        client.post('/receiving-reports/%s/submit' % rr.id, follow_redirects=True)
        notes = ' '.join(
            (e.notes or '') for e in
            AuditLog.query.filter_by(module='receiving_reports', record_id=rr.id).all())
        assert MEMO in notes
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov -k Resubmitting`
Expected: FAIL — `assert 'The goods were on PO-00985 after all.' is None`

- [ ] **Step 3: Clear the fields in `submit()`**

In `app/receiving_reports/views.py`, in `submit()`, replace:

```python
    rr.status = 'submitted'
    rr.submitted_by_id = current_user.id
    rr.submitted_at = ph_now()
    db.session.commit()
```

with:

```python
    rr.status = 'submitted'
    rr.submitted_by_id = current_user.id
    rr.submitted_at = ph_now()
    # Submitting starts a NEW cycle, so the previous one's memo stops applying. Leaving
    # it set made a freshly submitted receipt still read "Returned to draft: ..." --
    # describing a correction that has since been made.
    #
    # Cleared rather than merely hidden: no display rule keyed on status can tell a
    # current memo from a stale one, because the status is the same either way. The
    # provenance goes with it -- a returned_at with no return_reason says something
    # happened and refuses to say what.
    #
    # No history is lost: return_to_draft writes the full memo into the audit log,
    # which is the permanent record. These columns only ever held the current cycle.
    rr.return_reason = None
    rr.returned_by_id = None
    rr.returned_at = None
    db.session.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add app/receiving_reports/views.py tests/integration/test_rr_return_to_draft.py
git commit -m "fix(rr): clear the return memo when a receipt is re-submitted"
```

---

## Task 4: Detail page — the button, the modal, the memo

**Files:**
- Modify: `app/receiving_reports/templates/receiving_reports/detail.html`
- Test: `tests/integration/test_rr_return_to_draft.py`

**Interfaces:**
- Consumes: endpoint `receiving_reports.return_to_draft` from Task 2.
- Produces: DOM ids `returnModal`, and the memo block.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_rr_return_to_draft.py`:

```python
class TestTheDetailPage:

    def _page(self, client, rr):
        return client.get('/receiving-reports/%s' % rr.id).data.decode()

    def test_the_control_is_offered_on_a_submitted_receipt(self, client, db_session,
                                                           main_branch, vendor, product,
                                                           admin_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        body = self._page(client, rr)
        assert 'Return to Draft' in body
        assert 'id="returnModal"' in body

    def test_it_is_withheld_on_a_draft_receipt(self, client, db_session, main_branch,
                                               vendor, product, admin_user):
        """CONTROL. A control that can only fail is its own defect -- the route refuses
        a draft, so the page must not offer it."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user, status='draft',
                 number='RR-RTD-DRAFT')
        _login(client, admin_user, main_branch)
        assert 'Return to Draft' not in self._page(client, rr)

    def test_it_is_withheld_from_someone_who_may_not(self, client, db_session,
                                                     main_branch, vendor, product,
                                                     admin_user, staff_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, staff_user, main_branch)
        assert 'Return to Draft' not in self._page(client, rr)

    def test_the_memo_is_displayed_after_a_return(self, client, db_session, main_branch,
                                                  vendor, product, admin_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        body = self._page(client, rr)
        assert 'Returned to draft:' in body
        assert MEMO in body
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov -k DetailPage`
Expected: FAIL — `'Return to Draft' in body` is False.

- [ ] **Step 3: Add the button**

In `app/receiving_reports/templates/receiving_reports/detail.html`, immediately after the Approve block (the `{% endif %}` closing `rr.status in ['draft', 'submitted'] and can_approve`), insert:

```jinja
  {# Return to Draft. Offered to an approver OR to whoever submitted it -- the same
     rule views._may_return_to_draft enforces. Rendering it for anyone else would show
     a control that can only fail, which is the defect the Cancel button's comment
     above describes. #}
  {% set may_return = can_approve or (rr.submitted_by_id and rr.submitted_by_id == current_user.id) %}
  {% if rr.status == 'submitted' and may_return %}
  <button type="button" class="btn btn-secondary"
          onclick="document.getElementById('returnModal').style.display='flex'">Return to Draft</button>
  {% endif %}
```

- [ ] **Step 4: Add the modal**

Immediately after the closing `</div>` of the existing `cancelModal` block:

```jinja
<div id="returnModal" class="modal-overlay" style="display:none;align-items:center;justify-content:center;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:1000">
  <div class="card" style="max-width:480px;width:90%">
    <div class="card-body">
      <h3>Return Receiving Report to Draft</h3>
      <p class="text-muted" style="font-size:13px;">
        The receipt becomes editable again so its lines can be corrected &mdash; for
        example, replacing a no-PO line with the purchase order it turned out to belong
        to. Nothing has been posted yet.
      </p>
      <form method="POST" action="{{ url_for('receiving_reports.return_to_draft', id=rr.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div class="form-group">
          <label>Reason (at least 10 characters)</label>
          <textarea name="return_reason" class="form-control" rows="3" required minlength="10"></textarea>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">Return to Draft</button>
          <button type="button" class="btn btn-secondary" onclick="document.getElementById('returnModal').style.display='none'">Close</button>
        </div>
      </form>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Display the memo**

Find the block rendering `rr.remarks` in the detail card and add immediately after it:

```jinja
  {# Styled by KIND, using the .record-memo component added for purchase requisitions
     (app/static/css/style.css). Amber, not red: work handed back is not a failure. #}
  {% if rr.return_reason %}
  <p class="record-memo record-memo--returned"><strong>Returned to draft:</strong> {{ rr.return_reason }}</p>
  {% endif %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_rr_return_to_draft.py -q --no-cov`
Expected: PASS (all)

- [ ] **Step 7: Check for a forbidden dialog call**

Run: `python -m pytest tests/integration/test_rr_form_render.py -q --no-cov`
Expected: PASS. If `test_no_javascript_popup_is_used` fails, the markup or a comment contains the literal `alert(`, `confirm(` or `prompt(` — reword it.

- [ ] **Step 8: Commit**

```bash
git add app/receiving_reports/templates/receiving_reports/detail.html \
        tests/integration/test_rr_return_to_draft.py
git commit -m "feat(rr): Return to Draft control and memo on the receipt detail page"
```

---

## Task 5: Carry `product_id` into the open-lines payload

**Files:**
- Modify: `app/receiving_reports/views.py` (`_po_lines_payload`)
- Test: `tests/integration/test_rr_no_po_warning.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_po_lines_payload` rows gain `'product_id': int|None`. That helper feeds BOTH the edit page's server-rendered payload and the `/receiving-reports/open-lines` endpoint, so one field serves both. Task 6 indexes on it.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_rr_no_po_warning.py`:

```python
"""A no-PO line is flagged when the vendor has an open order line for that product.

Owner request 2026-09-07. PO-less receipts are expected weekly or more, so the mismatch
is caught at ENTRY rather than only repaired afterwards.

It WARNS, it does not block. The match is a heuristic: it knows this vendor has an open
line for this product, not that this carton came off that order. A free replacement, a
sample, or a second delivery are all legitimate direct receipts against an open order,
and blocking would make them unrecordable.

KNOWN LIMIT, by owner decision: the warning fires at pick time in the browser, and the
server stores the override reason WITHOUT refusing a line that lacks one. A raw POST, or
an order approved between picking and saving, gets past it. Recorded here so it is not
mistaken for an oversight.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.receiving_reports.models import ReceivingReport
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='WARN-V', name='Warning Test Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def other_vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='WARN-V2', name='Other Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def product(db_session):
    from app.products.models import Product
    p = Product(code='WARN-P', name='Warned Item', track_inventory=False, is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _open_po(db_session, branch, vendor, product, user, number='PO-WARN-1', qty='10'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number,
                       order_date=date(2026, 9, 1), vendor_id=vendor.id,
                       vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive', created_by_id=user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Ordered thing', quantity=Decimal(qty),
        unit_price=Decimal('100'), amount=Decimal(qty) * 100,
        product_id=product.id, vat_rate=Decimal('12')))
    db_session.add(po); db_session.commit()
    return po


class TestThePayloadCarriesTheProduct:

    def test_open_lines_name_their_product_id(self, client, db_session, main_branch,
                                              vendor, product, admin_user):
        """Without product_id the browser cannot match a chosen product to an open
        order line at all -- product_code is display text, not an identity.

        Asserted against the ENDPOINT, not the create page. On a fresh GET of
        /receiving-reports/create the view sets `eligible = []` deliberately -- there is
        no vendor until the receiver picks one -- so the page-load payload is empty and
        proves nothing. The endpoint is what the browser actually reads.
        """
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        rows = client.get('/receiving-reports/open-lines?vendor_id=%s'
                          % vendor.id).get_json()['lines']
        assert rows, 'the endpoint offered no open lines'
        assert rows[0]['product_id'] == product.id

    def test_another_vendors_open_line_is_not_offered(self, client, db_session,
                                                      main_branch, other_vendor,
                                                      vendor, product, admin_user):
        """CONTROL, and the reason the warning needs no vendor check of its own: the
        endpoint is already scoped, so a match can only ever be this vendor's."""
        _open_po(db_session, main_branch, other_vendor, product, admin_user,
                 number='PO-WARN-OTHER')
        _login(client, admin_user, main_branch)
        rows = client.get('/receiving-reports/open-lines?vendor_id=%s'
                          % vendor.id).get_json()['lines']
        assert rows == []
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_rr_no_po_warning.py -q --no-cov`
Expected: FAIL — the payload has no `product_id`.

- [ ] **Step 3: Add the field**

In `app/receiving_reports/views.py`, in `_po_lines_payload`, inside `rows.append({...})` add as the second entry:

```python
                # The browser matches a chosen product to open order lines on THIS.
                # product_code is display text and can repeat across products; the id
                # is the identity, so the warning is exact rather than approximate.
                'product_id': li.product_id,
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_rr_no_po_warning.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/receiving_reports/views.py tests/integration/test_rr_no_po_warning.py
git commit -m "feat(rr): carry product_id in the open purchase-order lines payload"
```

---

## Task 6: The pick-time warning

**Files:**
- Modify: `app/receiving_reports/templates/receiving_reports/form.html`
- Test: `tests/integration/test_rr_no_po_warning.py`

**Interfaces:**
- Consumes: `product_id` on the rows returned by `/receiving-reports/open-lines` (Task 5); the `vendorSelect` and `excludeRrId` bindings already declared in the picker block; `rrAddLine(row, qty)` and `rrAddDirectLine(r, qty, uom)` from the shipped work.
- Produces: `rrAddDirectLine(r, qty, uom, reason)` — a fourth optional argument; DOM ids `directPoWarning`, `directNoPoReason`; row attribute `data-reason`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_rr_no_po_warning.py`:

```python
class TestTheFormCanWarn:

    def _create_page(self, client, vendor):
        # No vendor_id query param: the create view ignores one on GET, and these
        # assertions are about STATIC markup that renders regardless.
        return client.get('/receiving-reports/create').data.decode()

    def test_the_modal_has_somewhere_to_show_the_warning(self, client, db_session,
                                                         main_branch, vendor, product,
                                                         admin_user):
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        assert 'id="directPoWarning"' in self._create_page(client, vendor)

    def test_the_modal_has_somewhere_to_type_the_override(self, client, db_session,
                                                          main_branch, vendor, product,
                                                          admin_user):
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        assert 'id="directNoPoReason"' in self._create_page(client, vendor)

    def test_no_blocking_dialog_is_used(self, client, db_session, main_branch, vendor,
                                        product, admin_user):
        """Project rule: no confirm()/alert()/prompt(), ever -- they wedge an automated
        browser until dismissed by hand. Comments count; the test scans served HTML."""
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        page = self._create_page(client, vendor)
        for banned in ('confirm(', 'alert(', 'prompt('):
            assert banned not in page, '%s is forbidden -- use inline HTML' % banned
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_rr_no_po_warning.py -q --no-cov -k FormCanWarn`
Expected: FAIL — the ids do not exist.

- [ ] **Step 3: Add the warning markup to the modal**

In `form.html`, inside `#directPickerModal`, immediately after the product `<select id="directProduct" ...></select>`:

```jinja
        {# Filled by script when the chosen product matches an open order line for this
           vendor. Hidden otherwise: a product with nothing to explain should show no
           explanation. #}
        <div id="directPoWarning" style="display:none;margin:0 0 12px;padding:9px 13px;
             border-radius:var(--radius);border-left:3px solid var(--amber);
             background:var(--alert-warning-bg);color:var(--alert-warning-text);font-size:13px;">
          <div id="directPoWarningText" style="margin-bottom:8px;"></div>
          <button type="button" class="btn btn-secondary" id="directUsePo"
                  style="padding:2px 10px;">Receive against the order instead</button>
          <label style="display:block;margin-top:10px;">
            It really had no purchase order &mdash; why?
            <input type="text" id="directNoPoReason" class="form-control"
                   maxlength="200" placeholder="e.g. free replacement for the damaged unit">
          </label>
        </div>
```

- [ ] **Step 4: Build the index and wire the warning**

In `form.html`, in the **picker block** (the second `<script>`, the one the DOM shim does not execute), inside the no-PO picker IIFE, after the `uomSel` fill loop:

```javascript
    // product_id -> [row] for the CURRENT vendor, rebuilt each time this modal opens.
    //
    // FETCHED, not read from the page-load payload: on a fresh create page the view
    // sets `eligible = []` on purpose -- there is no vendor until the receiver picks
    // one -- so PO_LINES is empty exactly when the warning matters most. The
    // open-lines endpoint is the same source the Pull picker uses, already scoped to
    // the selected vendor and already excluding this receipt, and its rows carry
    // po_number as well. Fetching on open also keeps the index current, which narrows
    // the window where an order is approved between picking and saving.
    let OPEN_BY_PRODUCT = {};

    function loadOpenLines() {
      const vendorId = chosenVendorId();
      OPEN_BY_PRODUCT = {};
      if (!vendorId) return Promise.resolve();
      const url = '/receiving-reports/open-lines?vendor_id=' + vendorId
                + (excludeRrId ? ('&exclude_rr_id=' + excludeRrId) : '');
      return fetch(url, {credentials: 'same-origin'})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          (d.lines || []).forEach(function (row) {
            if (!row.product_id || !(row.open > 0)) return;
            (OPEN_BY_PRODUCT[row.product_id] =
              OPEN_BY_PRODUCT[row.product_id] || []).push(row);
          });
        })
        .catch(function () { OPEN_BY_PRODUCT = {}; });   // a warning is guidance; its
                                                          // absence must never block a
                                                          // receipt from being recorded
    }

    const warnBox = document.getElementById('directPoWarning');
    const warnText = document.getElementById('directPoWarningText');
    const reasonInput = document.getElementById('directNoPoReason');
    const usePoBtn = document.getElementById('directUsePo');

    function matchesFor(productId) { return OPEN_BY_PRODUCT[productId] || []; }

    function refreshWarning() {
      const matches = matchesFor(parseInt(sel.value, 10));
      if (!matches.length) {
        warnBox.style.display = 'none';
        reasonInput.value = '';
        return;
      }
      warnText.textContent = 'This vendor has '
        + matches.map(function (m) { return m.open + ' open on ' + m.po_number; }).join(', ')
        + '.';
      warnBox.style.display = 'block';
    }
    sel.addEventListener('change', refreshWarning);

    // Switch to the ordered line: adds it through the SAME path the Pull picker uses,
    // so the ceiling and the vendor/branch/status guards apply unchanged. No direct
    // line is created at all.
    usePoBtn.addEventListener('click', function () {
      const row = matchesFor(parseInt(sel.value, 10))[0];
      if (!row) return;
      // The fetched row IS the shape rrAddLine expects -- it carries po_number,
      // ordered, received and open. This is the same call the Pull picker makes with
      // its own fetched row, so the ceiling and the vendor/branch/status guards apply
      // identically. No direct line is created.
      rrAddLine(row, qty.value || row.open);
      close();
    });
```

Then in the existing `directPickerAdd` handler, replace the add call:

```javascript
      rrAddDirectLine(p, qty.value, UNIT_INDEX[parseInt(uomSel.value, 10)]);
```

with:

```javascript
      // The reason travels with the line. Only meaningful when the warning fired --
      // a product with no matching order has nothing to explain.
      const reason = (warnBox.style.display === 'block')
        ? (reasonInput.value || '').trim() : '';
      if (warnBox.style.display === 'block' && !reason) {
        err.textContent = 'Say why this had no purchase order, or receive it against the order.';
        err.style.display = 'block';
        reasonInput.focus();
        return;
      }
      rrAddDirectLine(p, qty.value, UNIT_INDEX[parseInt(uomSel.value, 10)], reason);
```

And in the modal-open handler, after `uomSel.value = '';` add:

```javascript
      warnBox.style.display = 'none';          // no stale warning while the fetch runs
      loadOpenLines().then(refreshWarning);
```

**Before this works, lift two bindings out of the Pull picker's IIFE.** `excludeRrId`,
`RR_FIXED_VENDOR_ID` and `chosenVendorId()` are currently declared *inside* that
IIFE, so the no-PO picker cannot see them. Move all three to the top of the picker
`<script>` block, outside both IIFEs, changing nothing else:

```javascript
  const excludeRrId = {{ (rr.id if rr else 0) | tojson }};
  // On an EDIT the pickers ask the RECEIPT for its vendor, never the live select:
  // edit() scopes `eligible` by rr.vendor_id and ignores any POSTed vendor_id, so
  // reading the select would offer lines from a vendor the save must refuse.
  const RR_FIXED_VENDOR_ID = {{ (rr.vendor_id if rr else 0) | tojson }};
  function chosenVendorId() {
    if (RR_FIXED_VENDOR_ID) return RR_FIXED_VENDOR_ID;
    const sel = document.getElementById('vendorSelect');
    const v = sel ? parseInt(sel.value, 10) : 0;
    return v > 0 ? v : 0;      // 0 is the "-- Select vendor --" sentinel
  }
```

Sharing one definition matters more than saving the duplication: the edit-page rule is
subtle, and two copies would drift. Verify the exact current body before moving it —
copy it rather than retyping from this plan.

- [ ] **Step 5: Carry the reason through the row**

In the **line block** (first `<script>`), change `rrDirectRowHtml` and `rrAddDirectLine` to accept and emit a reason. Replace the signature line and the `<tr>` opening:

```javascript
  function rrDirectRowHtml(r, qty, uom, reason) {
    const item = r.product_name || r.product_code || '';
    const pid = escHtml(r.product_id);
    const uomId = uom && uom.id ? uom.id : '';
    const uomText = uom && uom.code ? uom.code : (r.uom || '');
    return '<tr class="rr-line rr-line--direct" data-product="' + pid + '"'
         + ' data-uom="' + escHtml(uomId) + '"'
         + ' data-reason="' + escHtml(reason || '') + '">'
```

and on the quantity input, after the `data-uom` attribute:

```javascript
         + ' data-reason="' + escHtml(reason || '') + '"'
```

and:

```javascript
  function rrAddDirectLine(r, qty, uom, reason) {
    if (!RR_ROW_COUNT) rrGridBody().innerHTML = '';
    rrGridBody().insertAdjacentHTML('beforeend', rrDirectRowHtml(r, qty, uom, reason));
    RR_ROW_COUNT += 1;
    return true;
  }
```

In the serialiser, in the `else if (inp.dataset.product)` branch, after the `unit_of_measure_id` line:

```javascript
        if (inp.dataset.reason) entry.no_po_reason = inp.dataset.reason;
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_rr_no_po_warning.py tests/integration/test_rr_form_render.py -q --no-cov`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/receiving_reports/templates/receiving_reports/form.html \
        tests/integration/test_rr_no_po_warning.py
git commit -m "feat(rr): warn at pick time when a no-PO line matches an open order"
```

---

## Task 7: Persist the override reason

**Files:**
- Modify: `app/receiving_reports/views.py` (`_parse_rr_lines`, `_existing_direct_lines`, `_submitted_existing_direct_lines`)
- Test: `tests/integration/test_rr_no_po_warning.py`

**Interfaces:**
- Consumes: `ReceivingReportItem.no_po_reason` from Task 1; the `no_po_reason` payload key from Task 6.
- Produces: `kept` entries become 5-tuples `(poi_id, product_id, qty, uom_id, reason)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_rr_no_po_warning.py`:

```python
def _create_via_form(client, vendor, payload, number='RR-WARN-FORM'):
    import json
    resp = client.post('/receiving-reports/create', data={
        'vendor_id': vendor.id, 'receipt_date': '2026-09-07', 'remarks': '',
        'rr_number': number, 'lines': json.dumps(payload),
    }, follow_redirects=True)
    return resp, ReceivingReport.query.filter_by(rr_number=number).first()


class TestTheReasonIsPersisted:

    def test_it_is_stored_on_the_line(self, client, db_session, main_branch, vendor,
                                      product, admin_user):
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2',
            'no_po_reason': 'Free replacement for the damaged unit'}])
        assert rr is not None, 'the receipt was refused'
        assert rr.line_items[0].no_po_reason == 'Free replacement for the damaged unit'

    def test_it_reaches_the_audit_log(self, client, db_session, main_branch, vendor,
                                      product, admin_user):
        """The column holds the current value; the audit log is the permanent record."""
        from app.audit.models import AuditLog
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2',
            'no_po_reason': 'Sample from the rep'}], number='RR-WARN-AUD')
        notes = ' '.join(
            (e.notes or '') for e in
            AuditLog.query.filter_by(module='receiving_reports', record_id=rr.id).all())
        assert 'Sample from the rep' in notes

    def test_a_line_with_no_reason_stores_none(self, client, db_session, main_branch,
                                               vendor, product, admin_user):
        """CONTROL: the field is optional. A direct line for a product with no matching
        order has nothing to explain, and a reason on it would be noise."""
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2'}],
            number='RR-WARN-NONE')
        assert rr is not None
        assert rr.line_items[0].no_po_reason is None

    def test_an_overlong_reason_is_truncated_not_refused(self, client, db_session,
                                                         main_branch, vendor, product,
                                                         admin_user):
        """A raw POST can send any length. Refusing would lose the receipt over a
        cosmetic problem; the text is capped instead."""
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2',
            'no_po_reason': 'x' * 500}], number='RR-WARN-LONG')
        assert rr is not None
        assert len(rr.line_items[0].no_po_reason) == 200

    def test_it_round_trips_into_the_edit_form(self, client, db_session, main_branch,
                                               vendor, product, admin_user):
        """Direct lines are re-rendered from their own channel; a reason that saved but
        did not come back would look like it had never been given."""
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2',
            'no_po_reason': 'Warranty swap'}], number='RR-WARN-RT')
        body = client.get('/receiving-reports/%s/edit' % rr.id).data.decode()
        assert 'Warranty swap' in body
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_rr_no_po_warning.py -q --no-cov -k ReasonIsPersisted`
Expected: FAIL — `assert None == 'Free replacement for the damaged unit'`

- [ ] **Step 3: Parse and store it**

In `_parse_rr_lines`, in the direct-line branch, immediately before `kept.append(...)`:

```python
            # Capped rather than refused: a raw POST can send any length, and losing a
            # whole receipt over a long sentence would be a worse outcome than a
            # shortened note. 200 matches the input's maxlength.
            reason = (d.get('no_po_reason') or '').strip()[:200] or None
```

Change the two `kept.append` calls to 5-tuples:

```python
            kept.append((poi_id, None, qty, None, None))     # PO-backed
```
```python
            kept.append((None, product_id, qty, uom_id, reason))   # direct
```

Change the builder loop header and the direct branch:

```python
    for line_number, (poi_id, product_id, qty, uom_id, reason) in enumerate(kept, start=1):
```
```python
            rr.line_items.append(ReceivingReportItem(
                line_number=line_number, purchase_order_item_id=None,
                product_id=product_id, received_quantity=qty,
                unit_of_measure_id=uom_id, no_po_reason=reason))
```

- [ ] **Step 4: Round-trip it through the edit form**

In `_existing_direct_lines`, add to the emitted dict:

```python
             'no_po_reason': li.no_po_reason,
```

In `_submitted_existing_direct_lines`, inside the `out.append({...})`:

```python
                        'no_po_reason': (d.get('no_po_reason') or None),
```

In `form.html`, in the `EXISTING_DIRECT.forEach` loop, pass it through:

```javascript
    if (r) rrAddDirectLine(r, d.received_quantity, UNIT_INDEX[d.unit_of_measure_id],
                           d.no_po_reason);
```

- [ ] **Step 5: Put the reason in the audit note**

Add this helper just above `_parse_rr_lines`:

```python
def _no_po_note(rr):
    """A one-line summary of any no-PO overrides on this receipt, for the audit note.

    The columns hold the CURRENT value and are rewritten wholesale whenever the receipt
    is saved -- edit() calls rr.line_items.clear() before re-parsing. The audit log is
    therefore the only place an overridden reason survives a later edit, which is what
    makes it the record worth reviewing.

    Returns None when nothing was overridden, so the ordinary receipt's audit entry is
    completely unchanged.
    """
    parts = ['%s: %s' % (li.product.code if li.product else li.line_number,
                         li.no_po_reason)
             for li in rr.line_items if li.no_po_reason]
    return ('No-PO reasons — ' + '; '.join(parts)) if parts else None
```

`create()` logs through `log_create(...)` and `edit()` through `log_update(...)` — **not
`log_audit`**. Both are thin shortcuts over `log_audit` and both already accept a
`notes=` keyword (`app/audit/utils.py:71,83`), so pass the helper's result to each.

In `create()`, change:

```python
            log_create(module='receiving_reports', record_id=rr.id,
                       record_identifier=f'{rr.rr_number} - {rr.vendor_name}',
                       new_values=model_to_dict(rr, ['rr_number', 'status', 'receipt_date']))
```

to:

```python
            log_create(module='receiving_reports', record_id=rr.id,
                       record_identifier=f'{rr.rr_number} - {rr.vendor_name}',
                       new_values=model_to_dict(rr, ['rr_number', 'status', 'receipt_date']),
                       notes=_no_po_note(rr))
```

In `edit()`, change:

```python
            log_update(module='receiving_reports', record_id=rr.id,
                       record_identifier=f'{rr.rr_number} - {rr.vendor_name}', old_values=old,
                       new_values=model_to_dict(rr, ['rr_number', 'status', 'receipt_date']))
```

to:

```python
            log_update(module='receiving_reports', record_id=rr.id,
                       record_identifier=f'{rr.rr_number} - {rr.vendor_name}', old_values=old,
                       new_values=model_to_dict(rr, ['rr_number', 'status', 'receipt_date']),
                       notes=_no_po_note(rr))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/ -q --no-cov -m receiving_reports`
Expected: PASS — all receiving_reports tests.

- [ ] **Step 7: Commit**

```bash
git add app/receiving_reports/views.py \
        app/receiving_reports/templates/receiving_reports/form.html \
        tests/integration/test_rr_no_po_warning.py
git commit -m "feat(rr): store the no-PO override reason on the line and in the audit log"
```

---

## Task 8: Make direct receipts findable

**Files:**
- Modify: `app/receiving_reports/templates/receiving_reports/list.html`
- Test: `tests/integration/test_rr_no_po_warning.py`

**Interfaces:**
- Consumes: `ReceivingReportItem.is_direct` (shipped in `d60062db`).
- Produces: nothing further.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_rr_no_po_warning.py`:

```python
class TestTheListShowsWhichReceiptsHadNoPo:
    """At weekly frequency these need reviewing without opening each one -- and this is
    the same view that shows whether the warning is working."""

    def test_a_receipt_with_a_direct_line_is_marked(self, client, db_session, main_branch,
                                                    vendor, product, admin_user):
        _login(client, admin_user, main_branch)
        _create_via_form(client, vendor, [{'product_id': product.id,
                                           'received_quantity': '2'}],
                         number='RR-WARN-LIST')
        body = client.get('/receiving-reports').data.decode()
        assert 'title="Contains items received without a purchase order"' in body

    def test_a_fully_ordered_receipt_is_not_marked(self, client, db_session, main_branch,
                                                   vendor, product, admin_user):
        """CONTROL. A marker on every row tells the reviewer nothing."""
        po = _open_po(db_session, main_branch, vendor, product, admin_user,
                      number='PO-WARN-LIST')
        _login(client, admin_user, main_branch)
        _create_via_form(client, vendor,
                         [{'purchase_order_item_id': po.line_items[0].id,
                           'received_quantity': '2'}], number='RR-WARN-PO')
        body = client.get('/receiving-reports').data.decode()
        assert 'title="Contains items received without a purchase order"' not in body
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/integration/test_rr_no_po_warning.py -q --no-cov -k ListShows`
Expected: FAIL — the marker is absent.

- [ ] **Step 3: Add the marker**

In `list.html`, in the cell rendering the receipt number, after the link:

```jinja
        {# Derived, not stored: `is_direct` reads the line's own FK, so this cannot
           drift from the lines themselves. #}
        {% if rr.line_items | selectattr('is_direct') | first %}
        <span title="Contains items received without a purchase order"
              style="margin-left:6px;color:var(--amber);font-weight:600;">no PO</span>
        {% endif %}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_rr_no_po_warning.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: Run the whole module and commit**

```bash
python -m pytest tests/ -q --no-cov -m receiving_reports
git add app/receiving_reports/templates/receiving_reports/list.html \
        tests/integration/test_rr_no_po_warning.py
git commit -m "feat(rr): mark receipts carrying items received without a purchase order"
```

---

## Task 9: Full verification

**Files:** none — verification only.

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q --no-cov`
Expected: **0 failed.** Baseline before this plan is 6828 passed / 6 skipped, plus the receiving-report work already on the branch.

- [ ] **Step 2: Drive it in a browser**

Nothing in this repository executes the form's JavaScript, so the tests above cannot cover the pick-time warning at all. Restart the dev server, then on `/receiving-reports/create`:

1. Choose a vendor with an open purchase order.
2. **+ Add Item Without PO** → choose a product on that order. The amber warning appears naming the order and its open quantity.
3. **Receive against the order instead** → the line lands as PO-backed, with Ordered / Already Received / Open filled in.
4. Repeat, this time typing a reason and adding it. The row shows **No PO**.
5. Save, submit, then **Return to Draft** with a memo. Reopen: the memo shows in amber, the reason survived on the line.
6. Submit again. The memo is gone.

- [ ] **Step 3: Update the spec's status**

In `docs/design/2026-09-07-rr-po-found-after-submit-design.md`, change the header line
`**Status:** design agreed, not yet implemented` to `**Status:** implemented`, and commit.

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| `product_id` in the open-lines payload | 5 |
| Pick-time warning naming the order and open quantity | 6 |
| "Receive against the order instead" uses the existing path | 6 |
| Override requires a reason before the line is added | 6 |
| `no_po_reason` per line, only when the warning fired | 1, 7 |
| Reason in the audit log | 7 |
| Return to Draft, `submitted` only | 1, 2 |
| Approver **or** submitter, failing closed on NULL | 2 |
| Memo ≥ 10 chars, stored and audit-logged | 2 |
| Memo cleared on re-submit, audit log keeps it | 3 |
| No auto-linking | 2 (route re-points nothing) |
| List marker for direct receipts | 8 |
| Four nullable columns, FK on the ORM side | 1 |
| Migration verified against a copy of the live database | 1 step 7 |
| Known limit recorded in code | 6 (module docstring of the test file) |

No gaps.

**Type consistency**

`rrAddDirectLine(r, qty, uom, reason)` — Task 6 defines the fourth parameter and Task 7's round-trip call passes it in the same position. `kept` is a 5-tuple in Task 7 and unpacked as a 5-tuple in the same task. `_may_return_to_draft(rr) -> bool` is defined in Task 2 step 3 and called in step 4. `RETURN_TO_DRAFT_STATUSES` is defined in Task 1 and read in Task 2.

**Placeholders:** none.
