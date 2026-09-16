# AP Attachment Amendment Request — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a posted AP Voucher that was approved without its required Signed AP be completed after the fact, through a request → approve → upload cycle that never touches posted financial content.

**Architecture:** An AP-specific request seam (`AccountsPayableAmendmentRequest`) mirroring `PurchaseRequestAmendmentRequest` — staff ASK without WRITE. The missing file is attached to the request and staged off-document; on approval the service commits it into the AP's own attachment table (`accounts_payable_attachments`, `kind='signed_ap'`) and marks the request approved, all in one transaction. Reject/withdraw discard the staged file. Nothing on the posted AP changes until approval.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, SQLite, Jinja templates, pytest. Launch/tests via `.\cas.ps1 philgen ...` and `pytest` (see Global Constraints).

**Spec:** `docs/design/2026-09-16-ap-attachment-amendment-request-design.md`

## Global Constraints

- **Time:** never `datetime.now()`. Use `ph_now()` (`from app.utils import ph_now`).
- **Migrations are hand-written:** `Migrate()` has no `render_as_batch`. `create_table` needs no batch wrapper; **name every FK constraint explicitly** inside `create_table`. Verify against a **copy of a real database**, not a `create_all()` test DB.
- **Branch scoping:** every new transactional/request model carries `branch_id` from day one; every list/lookup filters by branch.
- **Audit:** log through `app/audit/utils.py` (`log_create`); `log_audit`/`log_create` commit on their own and swallow exceptions — so write the attachment row and request status in the **business** transaction, not via the audit call.
- **BIR permanence:** no edit to a posted AP's amounts, VAT/WHT, or journal entry — this feature only adds an attachment row.
- **Tests:** `pytest` (single-threaded fine). Per-module marker `accounts_payable` is registered in `pytest.ini`; mark new tests `@pytest.mark.accounts_payable` + `@pytest.mark.integration` (or `unit`). Verify the audit log through the real HTTP route in route tests.
- **Local run:** never run `flask`/server by hand — `.\cas.ps1 philgen db upgrade`, `.\cas.ps1 philgen` (port 5050). Migration verification uses a copy of `instance/philgen.db`.

---

## File Structure

- **Create** `app/accounts_payable/amendment_models.py` — `AccountsPayableAmendmentRequest` (table `ap_amendment_requests`). One responsibility: the request row + its staged-file metadata + status helpers.
- **Create** `migrations/versions/apamd_0001_ap_amendment_requests.py` — additive `create_table`, named FKs.
- **Create** `app/accounts_payable/amendment_service.py` — request/withdraw/approve/reject, file staging + commit, branch/pending queries. One responsibility: the workflow logic, no HTTP.
- **Modify** `app/accounts_payable/views.py` — four thin routes (request / withdraw / approve / reject) + a review fetch helper; they parse the request, call the service, flash, redirect.
- **Modify** `app/accounts_payable/templates/accounts_payable/detail.html` — request control (posted + incomplete), pending-status + withdraw, approver review (staged-file preview + Approve/Reject).
- **Modify** `app/dashboard/action_items_service.py` — surface pending AP amendment requests in `gather_approval_items` and count them.
- **Tests:** `tests/integration/test_ap_amendment_request.py` (service + routes + Action Items), `tests/unit/test_ap_amendment_model.py` (model helpers).

Reference (read before starting): `app/purchase_requests/amendment_models.py`, `app/purchase_requests/amendment_service.py`, `migrations/versions/pramd_0001_pr_amendment_requests.py`, and in `app/accounts_payable/views.py` the helpers `_save_ap_attachment`, `_ap_upload_dir`, `_ATTACHMENT_ALLOWED`, and the `AccountsPayableAttachment` model.

---

### Task 1: Data model + migration

**Files:**
- Create: `app/accounts_payable/amendment_models.py`
- Create: `migrations/versions/apamd_0001_ap_amendment_requests.py`
- Test: `tests/unit/test_ap_amendment_model.py`

**Interfaces:**
- Produces: `AccountsPayableAmendmentRequest` with columns `id, ap_id, branch_id, requested_by_id, reason, kind, staged_original_filename, staged_stored_filename, staged_mime_type, staged_file_size, status, reviewed_by_id, reviewed_at, review_note, created_at, updated_at, row_version`; class constants `STATUS_PENDING='pending'`, `STATUS_APPROVED='approved'`, `STATUS_REJECTED='rejected'`, `STATUS_WITHDRAWN='withdrawn'`, `MIN_REASON_LEN=10`; property `is_pending`; relationships `ap`, `branch`, `requested_by`, `reviewed_by`. Migration revision `apamd_0001`, down_revision = current head (`reqatt_0001`).

- [ ] **Step 1: Write the failing model test**

```python
# tests/unit/test_ap_amendment_model.py
import pytest
pytestmark = [pytest.mark.accounts_payable, pytest.mark.unit]

def test_model_defaults_and_pending(db_session):
    from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest as R
    r = R(ap_id=1, branch_id=1, requested_by_id=1, reason='need signed copy', kind='signed_ap',
          staged_original_filename='s.pdf', staged_stored_filename='abc.pdf',
          staged_mime_type='application/pdf', staged_file_size=10)
    from app import db
    db.session.add(r); db.session.commit()
    assert r.status == R.STATUS_PENDING
    assert r.is_pending is True
    assert R.MIN_REASON_LEN == 10
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_ap_amendment_model.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: app.accounts_payable.amendment_models`.

- [ ] **Step 3: Write the model**

```python
# app/accounts_payable/amendment_models.py
"""Edit-level request to attach a missing REQUIRED file to an already-posted AP.

Mirrors PurchaseRequestAmendmentRequest: staff write only to THIS table; the
posted AP itself is touched exclusively by the approver-gated approve path, which
adds an AccountsPayableAttachment. Attachments only — no financial change, ever.
"""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned


class AccountsPayableAmendmentRequest(RowVersioned, db.Model):
    __tablename__ = 'ap_amendment_requests'
    __table_args__ = (db.Index('ix_ap_amend_req_pending', 'ap_id', 'status'),)

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_WITHDRAWN = 'withdrawn'
    MIN_REASON_LEN = 10

    id = db.Column(db.Integer, primary_key=True)
    ap_id = db.Column(db.Integer, db.ForeignKey('accounts_payable.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    # Slot the request fills. Always 'signed_ap' today; column keeps it general.
    kind = db.Column(db.String(40), nullable=False)
    # The file staged with the request (on disk under the request until approve).
    staged_original_filename = db.Column(db.String(255), nullable=False)
    staged_stored_filename = db.Column(db.String(255), nullable=False)
    staged_mime_type = db.Column(db.String(100), nullable=False)
    staged_file_size = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False, index=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    ap = db.relationship('AccountsPayable',
                         backref=db.backref('amendment_requests', lazy='dynamic'))
    branch = db.relationship('Branch', foreign_keys=[branch_id])
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    def __repr__(self):
        return '<APAmendmentRequest ap=%s status=%s>' % (self.ap_id, self.status)
```

Import it where models are registered: add `from app.accounts_payable import amendment_models  # noqa: F401` next to the existing accounts_payable model import in `app/__init__.py` (grep `accounts_payable.models` there and mirror it) so the table is created and the migration's autogen-independent registration is consistent.

- [ ] **Step 4: Write the migration**

```python
# migrations/versions/apamd_0001_ap_amendment_requests.py
"""AP attachment amendment requests: edit-level ask, approvers commit the file.

Purely ADDITIVE — one new table, no existing table altered. create_table needs no
batch wrapper; all FKs are NAMED so a later batch rebuild can reproduce them.

Revision ID: apamd_0001
Revises: reqatt_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'apamd_0001'
down_revision = 'reqatt_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ap_amendment_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ap_id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('staged_original_filename', sa.String(length=255), nullable=False),
        sa.Column('staged_stored_filename', sa.String(length=255), nullable=False),
        sa.Column('staged_mime_type', sa.String(length=100), nullable=False),
        sa.Column('staged_file_size', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id', name='pk_ap_amendment_requests'),
        sa.ForeignKeyConstraint(['ap_id'], ['accounts_payable.id'], name='fk_ap_amend_req_ap'),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name='fk_ap_amend_req_branch'),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], name='fk_ap_amend_req_requested_by'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], name='fk_ap_amend_req_reviewed_by'),
    )
    op.create_index('ix_ap_amendment_requests_ap_id', 'ap_amendment_requests', ['ap_id'])
    op.create_index('ix_ap_amendment_requests_branch_id', 'ap_amendment_requests', ['branch_id'])
    op.create_index('ix_ap_amendment_requests_status', 'ap_amendment_requests', ['status'])
    op.create_index('ix_ap_amend_req_pending', 'ap_amendment_requests', ['ap_id', 'status'])


def downgrade():
    op.drop_index('ix_ap_amend_req_pending', table_name='ap_amendment_requests')
    op.drop_index('ix_ap_amendment_requests_status', table_name='ap_amendment_requests')
    op.drop_index('ix_ap_amendment_requests_branch_id', table_name='ap_amendment_requests')
    op.drop_index('ix_ap_amendment_requests_ap_id', table_name='ap_amendment_requests')
    op.drop_table('ap_amendment_requests')
```

- [ ] **Step 5: Run the model test — verify it passes**

Run: `python -m pytest tests/unit/test_ap_amendment_model.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Verify the migration up/down on a copy of the real DB**

```bash
cd /c/envs/workspace/cas && rm -f instance/apamd_probe.db && cp instance/philgen.db instance/apamd_probe.db
SQLALCHEMY_DATABASE_URI="sqlite:///apamd_probe.db" python -m flask db upgrade
SQLALCHEMY_DATABASE_URI="sqlite:///apamd_probe.db" python -c "import sqlite3;print('ap_amendment_requests' in [r[0] for r in sqlite3.connect('instance/apamd_probe.db').execute(\"select name from sqlite_master where type='table'\")])"
SQLALCHEMY_DATABASE_URI="sqlite:///apamd_probe.db" python -m flask db downgrade reqatt_0001
rm -f instance/apamd_probe.db
```
Expected: upgrade runs `reqatt_0001 -> apamd_0001`; the print is `True`; downgrade runs cleanly.

- [ ] **Step 7: Commit**

```bash
git add app/accounts_payable/amendment_models.py migrations/versions/apamd_0001_ap_amendment_requests.py app/__init__.py tests/unit/test_ap_amendment_model.py
git commit -m "feat(ap-amend): task 1 — AccountsPayableAmendmentRequest model + migration"
```

---

### Task 2: Service layer (request / withdraw / approve / reject)

**Files:**
- Create: `app/accounts_payable/amendment_service.py`
- Test: `tests/integration/test_ap_amendment_request.py`

**Interfaces:**
- Consumes: `AccountsPayableAmendmentRequest` (Task 1); AP helpers `_ap_upload_dir`, `_ATTACHMENT_ALLOWED` and model `AccountsPayableAttachment` from `app/accounts_payable`; `missing_required` from `app.attachments.completeness`.
- Produces:
  - `class APAmendmentError(ValueError)`
  - `pending_request_for(ap_id) -> AccountsPayableAmendmentRequest | None`
  - `pending_requests_for_branches(branch_ids) -> list`
  - `create_request(ap, user, reason, file_storage) -> req` (adds + stages file; caller commits)
  - `withdraw_request(req, user) -> req`
  - `approve_request(req, approver) -> AccountsPayableAttachment` (commits the file into the AP)
  - `reject_request(req, approver, note=None) -> req`
  - `_staged_dir(req_id) -> str` (helper: `instance/uploads/ap_amendment_requests/<req_id>/`)

- [ ] **Step 1: Write the failing service tests**

```python
# tests/integration/test_ap_amendment_request.py
import io
from datetime import date
from decimal import Decimal
import pytest
from app import db
pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]

def _posted_incomplete_ap(db_session, main_branch):
    from app.accounts_payable.models import AccountsPayable
    from app.customers.models import Customer  # noqa: not needed; AP uses vendor
    from app.vendors.models import Vendor
    v = Vendor(code='APV9', name='Amend Vendor', check_payee_name='Amend Vendor',
               is_active=True, payment_terms='Net 30')
    db_session.add(v); db_session.commit()
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-AMEND-1',
                         ap_date=date(2026, 9, 16), due_date=date(2026, 10, 16),
                         vendor_id=v.id, vendor_name=v.name, status='posted',
                         total_amount=Decimal('100'), notes='')
    db_session.add(ap); db_session.commit()
    return ap

def _fs(name='signed.pdf', data=b'%PDF-1.4'):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type='application/pdf')

def test_create_stages_file_and_stays_pending(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, _staged_dir
    import os
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'signed copy arrived late', _fs())
    db.session.commit()
    assert req.is_pending and req.kind == 'signed_ap'
    assert os.path.isfile(os.path.join(_staged_dir(req.id), req.staged_stored_filename))
    # Nothing committed onto the AP yet.
    from app.accounts_payable.models import AccountsPayableAttachment
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0

def test_approve_commits_file_into_ap_and_clears_slot(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, approve_request
    from app.accounts_payable.models import AccountsPayableAttachment
    from app.attachments.completeness import missing_required
    ap = _posted_incomplete_ap(db_session, main_branch)
    assert 'signed_ap' in [s.key for s in missing_required('accounts_payable', ap)]
    req = create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    att = approve_request(req, admin_user); db.session.commit()
    assert att.kind == 'signed_ap' and att.ap_id == ap.id
    assert req.status == 'approved' and req.reviewed_by_id == admin_user.id
    assert missing_required('accounts_payable', ap) == []   # slot now filled

def test_reject_discards_staged_file(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, reject_request, _staged_dir
    from app.accounts_payable.models import AccountsPayableAttachment
    import os
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'wrong file attached', _fs()); db.session.commit()
    staged = os.path.join(_staged_dir(req.id), req.staged_stored_filename)
    reject_request(req, admin_user, 'not the signed AP'); db.session.commit()
    assert req.status == 'rejected'
    assert not os.path.exists(staged)
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0

def test_second_pending_request_refused(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, APAmendmentError
    ap = _posted_incomplete_ap(db_session, main_branch)
    create_request(ap, admin_user, 'first request here', _fs()); db.session.commit()
    with pytest.raises(APAmendmentError):
        create_request(ap, admin_user, 'second request here', _fs())

def test_request_refused_when_not_incomplete(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, approve_request, APAmendmentError
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'signed copy arrived', _fs()); db.session.commit()
    approve_request(req, admin_user); db.session.commit()   # slot now filled
    with pytest.raises(APAmendmentError):
        create_request(ap, admin_user, 'another signed copy', _fs())
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/integration/test_ap_amendment_request.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: app.accounts_payable.amendment_service`.

- [ ] **Step 3: Write the service**

```python
# app/accounts_payable/amendment_service.py
"""Attachments-only amendment workflow for a posted AP. Staff ask; approvers
commit the file. No financial change to the posted voucher — the approve path
only adds an AccountsPayableAttachment (kind='signed_ap')."""
import os
import uuid

from flask import current_app

from app import db
from app.utils import ph_now
from app.audit.utils import log_create
from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest as Req


class APAmendmentError(ValueError):
    """Precondition failure surfaced to the user as a flash, never a 500."""


def _staged_dir(req_id):
    path = os.path.join(current_app.config['UPLOAD_FOLDER'],
                        'ap_amendment_requests', str(req_id))
    os.makedirs(path, exist_ok=True)
    return path


def pending_request_for(ap_id):
    return (Req.query
            .filter_by(ap_id=ap_id, status=Req.STATUS_PENDING)
            .order_by(Req.id.desc()).first())


def pending_requests_for_branches(branch_ids):
    if not branch_ids:
        return []
    return (Req.query
            .filter(Req.status == Req.STATUS_PENDING, Req.branch_id.in_(branch_ids))
            .order_by(Req.id.desc()).all())


def _missing_required_keys(ap):
    from app.attachments.completeness import missing_required
    return {s.key for s in missing_required('accounts_payable', ap)}


def create_request(ap, user, reason, file_storage):
    """Stage a file against a posted, incomplete AP. Adds to session; caller commits."""
    from app.accounts_payable.views import _ATTACHMENT_ALLOWED
    from werkzeug.utils import secure_filename

    reason = (reason or '').strip()
    if len(reason) < Req.MIN_REASON_LEN:
        raise APAmendmentError('Give a reason of at least %d characters — it becomes the '
                               'permanent record of why this posted AP was completed.'
                               % Req.MIN_REASON_LEN)
    if ap.status not in ('posted', 'partially_paid', 'paid'):
        raise APAmendmentError('Only a posted AP can have an attachment amendment request.')
    missing = _missing_required_keys(ap)
    if 'signed_ap' not in missing:
        raise APAmendmentError('This AP is not missing any required file.')
    if pending_request_for(ap.id) is not None:
        raise APAmendmentError('This AP already has an amendment request awaiting review.')

    original_name = secure_filename(file_storage.filename or '')
    if not original_name:
        raise APAmendmentError('Invalid filename.')
    _, ext = os.path.splitext(original_name); ext = ext.lower()
    mime_type = _ATTACHMENT_ALLOWED.get(ext)
    if mime_type is None:
        raise APAmendmentError('File type "%s" is not allowed. Accepted: %s'
                               % (ext or 'unknown', ', '.join(sorted(_ATTACHMENT_ALLOWED))))

    req = Req(ap_id=ap.id, branch_id=ap.branch_id, requested_by_id=user.id,
              reason=reason, kind='signed_ap',
              staged_original_filename=original_name,
              staged_stored_filename='',        # set after we know the id
              staged_mime_type=mime_type, staged_file_size=0)
    db.session.add(req)
    db.session.flush()                          # assigns req.id

    stored_name = uuid.uuid4().hex + ext
    path = os.path.join(_staged_dir(req.id), stored_name)
    file_storage.save(path)
    req.staged_stored_filename = stored_name
    req.staged_file_size = os.path.getsize(path)
    return req


def withdraw_request(req, user):
    if not req.is_pending:
        raise APAmendmentError('This request has already been %s.' % req.status)
    if req.requested_by_id != user.id and not (user.has_full_access or user.role == 'accountant'):
        raise APAmendmentError('Only the requester or an approver can withdraw this request.')
    _delete_staged(req)
    req.status = Req.STATUS_WITHDRAWN
    return req


def reject_request(req, approver, note=None):
    if not req.is_pending:
        raise APAmendmentError('This request has already been %s.' % req.status)
    _delete_staged(req)
    req.status = Req.STATUS_REJECTED
    req.reviewed_by_id = approver.id
    req.reviewed_at = ph_now()
    req.review_note = (note or '').strip() or None
    return req


def approve_request(req, approver):
    """Commit the staged file into the AP as an AccountsPayableAttachment. Adds to
    session and commits (mirrors _save_ap_attachment's own-commit). Returns the row."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableAttachment
    from app.accounts_payable.views import _ap_upload_dir

    if not req.is_pending:
        raise APAmendmentError('This request has already been %s.' % req.status)
    ap = db.session.get(AccountsPayable, req.ap_id)
    if ap is None or ap.status not in ('posted', 'partially_paid', 'paid'):
        raise APAmendmentError('This AP can no longer take an attachment amendment.')
    # Authoritative re-check: the slot must still be empty at commit time.
    if req.kind not in _missing_required_keys(ap):
        _delete_staged(req)
        req.status = Req.STATUS_REJECTED
        req.reviewed_by_id = approver.id; req.reviewed_at = ph_now()
        req.review_note = 'Already completed before approval.'
        db.session.commit()
        raise APAmendmentError('The required file was already added; nothing to approve.')

    staged = os.path.join(_staged_dir(req.id), req.staged_stored_filename)
    dest_name = uuid.uuid4().hex + os.path.splitext(req.staged_original_filename)[1].lower()
    dest = os.path.join(_ap_upload_dir(ap.id), dest_name)
    import shutil
    shutil.copyfile(staged, dest)

    att = AccountsPayableAttachment(
        ap_id=ap.id, original_filename=req.staged_original_filename,
        stored_filename=dest_name, mime_type=req.staged_mime_type,
        file_size=req.staged_file_size, uploaded_by_id=req.requested_by_id, kind=req.kind)
    db.session.add(att)
    req.status = Req.STATUS_APPROVED
    req.reviewed_by_id = approver.id
    req.reviewed_at = ph_now()
    db.session.commit()

    log_create(module='accounts_payable_attachment', record_id=att.id,
               record_identifier='%s / %s' % (ap.ap_number, att.original_filename),
               new_values={'ap_id': ap.id, 'kind': att.kind,
                           'original_filename': att.original_filename,
                           'via': 'amendment_request', 'request_id': req.id})
    _delete_staged(req)
    return att


def _delete_staged(req):
    if not req.staged_stored_filename:
        return
    path = os.path.join(_staged_dir(req.id), req.staged_stored_filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            current_app.logger.warning('Could not remove staged AP amendment file: %s', path)
```

- [ ] **Step 4: Run the service tests — verify they pass**

Run: `python -m pytest tests/integration/test_ap_amendment_request.py -q -p no:cacheprovider`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/accounts_payable/amendment_service.py tests/integration/test_ap_amendment_request.py
git commit -m "feat(ap-amend): task 2 — request/withdraw/approve/reject service with file staging"
```

---

### Task 3: Routes

**Files:**
- Modify: `app/accounts_payable/views.py` (add four routes + a fetch helper near the other AP routes)
- Test: `tests/integration/test_ap_amendment_request.py` (append route tests)

**Interfaces:**
- Consumes: the Task 2 service functions; existing AP auth decorators. Find the AP module's edit-level and approve-level gates by grepping `views.py` for how `post` (approve-level) and attachment upload (edit-level) are gated, and reuse those exact decorators/checks.
- Produces routes:
  - `POST /accounts-payable/<int:id>/request-amendment` (edit-level)
  - `POST /accounts-payable/amendment-requests/<int:req_id>/withdraw` (requester/approver)
  - `POST /accounts-payable/amendment-requests/<int:req_id>/approve` (approve-level)
  - `POST /accounts-payable/amendment-requests/<int:req_id>/reject` (approve-level)

- [ ] **Step 1: Write the failing route tests**

```python
# append to tests/integration/test_ap_amendment_request.py
def _login(client, username='admin', password='admin123', branch=None):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    if branch is not None:
        with client.session_transaction() as s:
            s['selected_branch_id'] = branch.id

def test_route_request_then_approve_commits(client, db_session, admin_user, main_branch):
    from app.accounts_payable.models import AccountsPayableAttachment
    ap = _posted_incomplete_ap(db_session, main_branch)
    _login(client, branch=main_branch)
    r = client.post(f'/accounts-payable/{ap.id}/request-amendment',
                    data={'reason': 'signed copy arrived late',
                          'attachment': (io.BytesIO(b'%PDF-1.4'), 'signed.pdf')},
                    content_type='multipart/form-data')
    assert r.status_code in (302, 200)
    from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest as Req
    req = Req.query.filter_by(ap_id=ap.id).first()
    assert req is not None and req.is_pending
    r = client.post(f'/accounts-payable/amendment-requests/{req.id}/approve', follow_redirects=True)
    assert r.status_code == 200
    db_session.refresh(req)
    assert req.status == 'approved'
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id, kind='signed_ap').count() == 1

def test_route_reject_leaves_ap_untouched(client, db_session, admin_user, main_branch):
    from app.accounts_payable.models import AccountsPayableAttachment
    from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest as Req
    ap = _posted_incomplete_ap(db_session, main_branch)
    _login(client, branch=main_branch)
    client.post(f'/accounts-payable/{ap.id}/request-amendment',
                data={'reason': 'wrong file here', 'attachment': (io.BytesIO(b'%PDF-1.4'), 'x.pdf')},
                content_type='multipart/form-data')
    req = Req.query.filter_by(ap_id=ap.id).first()
    client.post(f'/accounts-payable/amendment-requests/{req.id}/reject',
                data={'note': 'not the signed AP'}, follow_redirects=True)
    db_session.refresh(req)
    assert req.status == 'rejected'
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/integration/test_ap_amendment_request.py -q -p no:cacheprovider -k route`
Expected: FAIL — 404 (routes not defined).

- [ ] **Step 3: Add the routes** (place near the AP attachment routes in `app/accounts_payable/views.py`; match the file's existing blueprint name `accounts_payable_bp`, its edit-level decorator used by the create/upload path, and its approve-level decorator used by `post`)

```python
# app/accounts_payable/views.py  (imports at top, with the other local imports)
from app.accounts_payable.amendment_service import (
    APAmendmentError, create_request, withdraw_request, approve_request, reject_request)


@accounts_payable_bp.route('/accounts-payable/<int:id>/request-amendment', methods=['POST'])
@login_required
@staff_or_above_required   # <-- use the SAME edit-level decorator the AP create/upload path uses
def request_amendment(id):
    ap = _get_ap_or_404(id)                     # reuse the module's existing fetch+branch guard
    f = request.files.get('attachment')
    if not f or not f.filename:
        flash('Attach the required file to request an amendment.', 'error')
        return redirect(url_for('accounts_payable.view', id=id))
    try:
        create_request(ap, current_user, request.form.get('reason'), f)
        db.session.commit()
        flash('Amendment request submitted for approval.', 'success')
    except APAmendmentError as e:
        db.session.rollback()
        flash(str(e), 'error')
    return redirect(url_for('accounts_payable.view', id=id))


def _get_ap_amend_req_or_404(req_id):
    from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest
    req = db.session.get(AccountsPayableAmendmentRequest, req_id)
    if req is None:
        abort(404)
    # Branch guard: the request must be in a branch the user can reach.
    from app.users.utils import get_accessible_branches
    if req.branch_id not in {b.id for b in get_accessible_branches(current_user)}:
        abort(404)
    return req


@accounts_payable_bp.route('/accounts-payable/amendment-requests/<int:req_id>/withdraw', methods=['POST'])
@login_required
@staff_or_above_required
def withdraw_amendment(req_id):
    req = _get_ap_amend_req_or_404(req_id); ap_id = req.ap_id
    try:
        withdraw_request(req, current_user); db.session.commit()
        flash('Amendment request withdrawn.', 'success')
    except APAmendmentError as e:
        db.session.rollback(); flash(str(e), 'error')
    return redirect(url_for('accounts_payable.view', id=ap_id))


@accounts_payable_bp.route('/accounts-payable/amendment-requests/<int:req_id>/approve', methods=['POST'])
@login_required
@accountant_or_admin_required   # <-- the SAME approve-level decorator the AP `post` route uses
def approve_amendment(req_id):
    req = _get_ap_amend_req_or_404(req_id); ap_id = req.ap_id
    try:
        approve_request(req, current_user)      # commits internally
        flash('Amendment approved; the required file is now on the AP.', 'success')
    except APAmendmentError as e:
        db.session.rollback(); flash(str(e), 'error')
    return redirect(url_for('accounts_payable.view', id=ap_id))


@accounts_payable_bp.route('/accounts-payable/amendment-requests/<int:req_id>/reject', methods=['POST'])
@login_required
@accountant_or_admin_required
def reject_amendment(req_id):
    req = _get_ap_amend_req_or_404(req_id); ap_id = req.ap_id
    try:
        reject_request(req, current_user, request.form.get('note')); db.session.commit()
        flash('Amendment request rejected.', 'info')
    except APAmendmentError as e:
        db.session.rollback(); flash(str(e), 'error')
    return redirect(url_for('accounts_payable.view', id=ap_id))
```

Note: the decorator names above (`staff_or_above_required`, `accountant_or_admin_required`, `_get_ap_or_404`, `_ap_upload_dir`, `_ATTACHMENT_ALLOWED`) are the ones this module already uses — confirm each by grep in `app/accounts_payable/views.py` before writing, and substitute the module's actual names if they differ.

- [ ] **Step 4: Run the route tests — verify they pass**

Run: `python -m pytest tests/integration/test_ap_amendment_request.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add app/accounts_payable/views.py tests/integration/test_ap_amendment_request.py
git commit -m "feat(ap-amend): task 3 — request/withdraw/approve/reject routes"
```

---

### Task 4: AP detail-page UI

**Files:**
- Modify: `app/accounts_payable/templates/accounts_payable/detail.html` (in the Attachments section, ~line 383)
- Modify: `app/accounts_payable/views.py` (`view`: pass the pending request + whether the AP is incomplete into the template context)
- Test: `tests/integration/test_ap_amendment_request.py` (append a render test)

**Interfaces:**
- Consumes: `pending_request_for` (Task 2), `attachment_incomplete_count('accounts_payable', ap)` (already used on this page), the four routes (Task 3).
- Produces: template blocks keyed off `ap_incomplete`, `ap_amend_pending`, and the user's level (`can_request`, `can_approve`).

- [ ] **Step 1: Write the failing render test**

```python
# append to tests/integration/test_ap_amendment_request.py
def test_detail_shows_request_control_when_posted_incomplete(client, db_session, admin_user, main_branch):
    ap = _posted_incomplete_ap(db_session, main_branch)
    _login(client, branch=main_branch)
    body = client.get(f'/accounts-payable/{ap.id}').get_data(as_text=True)
    assert 'request-amendment' in body        # the request form action is present
    assert 'Signed AP' in body                # names the missing required file

def test_detail_shows_pending_then_approve_control(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request
    ap = _posted_incomplete_ap(db_session, main_branch)
    create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    _login(client, branch=main_branch)
    body = client.get(f'/accounts-payable/{ap.id}').get_data(as_text=True)
    assert '/approve' in body and '/reject' in body    # approver review controls
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/integration/test_ap_amendment_request.py -q -p no:cacheprovider -k detail`
Expected: FAIL — request form/controls absent.

- [ ] **Step 3: Pass context from the `view` route**

In `app/accounts_payable/views.py`, in the `view(id)` function (grep `def view(` in this module), before `render_template('accounts_payable/detail.html', ...)`, add:

```python
from app.accounts_payable.amendment_service import pending_request_for
from app.attachments.completeness import missing_required
_ap_missing = [s.label for s in missing_required('accounts_payable', ap)]
_ap_amend_pending = pending_request_for(ap.id)
```

and pass into the template call: `ap_missing_labels=_ap_missing, ap_amend_pending=_ap_amend_pending`.

- [ ] **Step 4: Add the UI block** in `accounts_payable/detail.html`, inside the Attachments card (after the file list near line 405). `can_write`/role flags already exist on this page — reuse whatever the page already uses for edit-level (grep the template for an existing `can_` flag; else gate the request form with `current_user` role check mirroring the page's edit controls):

```html
{# --- Attachment amendment (posted + required file missing) --- #}
{% if ap.status in ['posted','partially_paid','paid'] and attachment_incomplete_count('accounts_payable', ap) %}
  <div class="card" style="margin-top:12px; border:1px solid var(--alert-warning-bg,#f0d9a0);">
    <div class="card-body">
      <div style="font-weight:600; margin-bottom:6px;">
        Missing required file: {{ ap_missing_labels|join(', ') }}
      </div>
      {% if ap_amend_pending %}
        <p style="color:var(--text-2); font-size:13px;">
          Amendment requested by {{ ap_amend_pending.requested_by.full_name }}
          — {{ ap_amend_pending.staged_original_filename }}. Awaiting approval.
        </p>
        {% if current_user.has_full_access or current_user.role == 'accountant' %}
          <div style="display:flex; gap:8px;">
            <form method="POST" action="{{ url_for('accounts_payable.approve_amendment', req_id=ap_amend_pending.id) }}">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
              <button class="btn btn-primary" type="submit">Approve &amp; attach</button>
            </form>
            <form method="POST" action="{{ url_for('accounts_payable.reject_amendment', req_id=ap_amend_pending.id) }}">
              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
              <input type="text" name="note" placeholder="Reason (optional)" style="font-size:12px;"/>
              <button class="btn btn-secondary" type="submit">Reject</button>
            </form>
          </div>
        {% endif %}
        {% if ap_amend_pending.requested_by_id == current_user.id %}
          <form method="POST" action="{{ url_for('accounts_payable.withdraw_amendment', req_id=ap_amend_pending.id) }}" style="margin-top:6px;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
            <button class="btn btn-secondary" type="submit">Withdraw request</button>
          </form>
        {% endif %}
      {% else %}
        <form method="POST" enctype="multipart/form-data"
              action="{{ url_for('accounts_payable.request_amendment', id=ap.id) }}"
              style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
          <input type="file" name="attachment" required>
          <input type="text" name="reason" placeholder="Reason (required, 10+ chars)" required style="min-width:220px;">
          <button class="btn btn-primary" type="submit">Request amendment to attach</button>
        </form>
      {% endif %}
    </div>
  </div>
{% endif %}
```

- [ ] **Step 5: Run the render tests — verify they pass**

Run: `python -m pytest tests/integration/test_ap_amendment_request.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/accounts_payable/views.py app/accounts_payable/templates/accounts_payable/detail.html tests/integration/test_ap_amendment_request.py
git commit -m "feat(ap-amend): task 4 — AP detail request/approve/reject UI"
```

---

### Task 5: Action Items surfacing

**Files:**
- Modify: `app/dashboard/action_items_service.py` (`gather_approval_items` + `count_action_items`)
- Test: `tests/integration/test_ap_amendment_request.py` (append)

**Interfaces:**
- Consumes: `pending_requests_for_branches` (Task 2), `get_accessible_branches`.
- Produces: For-Approval items shaped like the existing ones (`type, icon, id, desc, by, when, state, reviewURL`? — match the exact keys the other `gather_approval_items` entries use; the PR amendment block is the template).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_ap_amendment_request.py
def test_pending_request_appears_in_approval_items_and_count(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request
    from app.dashboard.action_items_service import gather_approval_items, count_action_items
    ap = _posted_incomplete_ap(db_session, main_branch)
    create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    items = gather_approval_items(admin_user)
    assert any('AP-AMEND-1' in (i.get('id') or '') and 'Signed AP' in (i.get('desc') or '')
               for i in items)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    # count is branch-scoped; call the same way the sidebar does
    assert count_action_items(admin_user, main_branch.id) >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/integration/test_ap_amendment_request.py -q -p no:cacheprovider -k approval_items`
Expected: FAIL — the AP request is not surfaced.

- [ ] **Step 3: Add the AP block to `gather_approval_items`** (right after the PR amendment block; mirror its branch-scoping and item shape exactly)

```python
    # AP attachment amendment requests — branch-scoped, approve-level only.
    from app.accounts_payable.amendment_service import pending_requests_for_branches as _ap_pending
    for req in _ap_pending({b.id for b in get_accessible_branches(user)}):
        ap = req.ap
        items.append({
            'type': 'AP Amendment',
            'icon': '📎',
            'id': ap.ap_number if ap else '#%s' % req.ap_id,
            'desc': 'AP amendment: attach %s' % req.staged_original_filename,
            'by': req.requested_by.full_name if req.requested_by else '—',
            'when': req.created_at.strftime('%Y-%m-%d %H:%M') if req.created_at else '—',
            'state': 'Pending',
            'reviewUrl': url_for('accounts_payable.view', id=req.ap_id),
        })
```

(`get_accessible_branches` and `url_for` are already imported in `gather_approval_items`; if `url_for` is not, add `from flask import url_for` at the top of the function as the PR block does. Match the exact key names — `reviewUrl` vs `reviewURL` — used by the surrounding items.)

- [ ] **Step 4: Add to `count_action_items`** in the approve-level branch (where PR amendment requests are counted), add:

```python
        from app.accounts_payable.amendment_service import pending_requests_for_branches as _ap_pending
        n += len(_ap_pending({b.id for b in get_accessible_branches(user)}))
```

(Place it inside the existing `if user.has_full_access or user.role == 'accountant':` block, alongside the PR `pending_requests_for_branches` count, so list and badge stay in lockstep.)

- [ ] **Step 5: Run the test — verify it passes**

Run: `python -m pytest tests/integration/test_ap_amendment_request.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 6: Full regression on the touched modules**

Run: `python -m pytest -m accounts_payable -q -p no:cacheprovider` then `python -m pytest tests/integration/test_action_items.py tests/integration/test_action_items_pr_approvals.py tests/integration/test_attachment_action_items.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/dashboard/action_items_service.py tests/integration/test_ap_amendment_request.py
git commit -m "feat(ap-amend): task 5 — pending AP amendment requests in Action Items"
```

---

## Self-Review

**Spec coverage:**
- Data model (spec §1) → Task 1. Lifecycle/states (§2) → Task 2 (create/withdraw/approve/reject + pending guard + commit re-check). File staging (§3) → Task 2 (`_staged_dir`, stage on create, commit/delete on approve, delete on reject/withdraw). Surfacing (§4) → Task 4 (detail) + Task 5 (Action Items). Permissions (§5) → Task 3 decorators + Task 4 gating. Edge cases (§6): voided/slot-filled re-check → Task 2 `approve_request`; config-frozen badge → unchanged (existing behavior); audit-swallow → attachment written in business txn (Task 2). All sections covered.

**Placeholder scan:** no TBD/TODO; every code step has real code. The one deliberate "confirm the module's actual decorator/helper names by grep" notes (Task 3/4) are because those names live in a large existing file the executor must read; the expected names are given, with instruction to substitute if the grep differs — not a placeholder for logic.

**Type consistency:** `AccountsPayableAmendmentRequest` (aliased `Req`) fields and `STATUS_*`/`MIN_REASON_LEN` constants are used identically across Tasks 1–5; service function names (`create_request`, `withdraw_request`, `approve_request`, `reject_request`, `pending_request_for`, `pending_requests_for_branches`, `_staged_dir`, `APAmendmentError`) match between Task 2 definitions and Tasks 3–5 call sites; route endpoint names (`accounts_payable.request_amendment/withdraw_amendment/approve_amendment/reject_amendment`) match between Task 3 and the Task 4 template.

---

## Execution Handoff

**Plan complete and saved to `docs/design/2026-09-16-ap-attachment-amendment-request-plan.md`** (kept beside the spec, per this repo's `docs/design/` convention, rather than the skill's default `docs/superpowers/plans/`).

Two execution options:
1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute here with checkpoints.

Which approach?
