# Document Attachments (PR, PO, RR, CV) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users attach unlimited files/images to Purchase Requisitions, Purchase Orders, Receiving Reports and Cash Disbursement Vouchers while the document is not yet approved (and, for PR/PO, through the amendment path), with AP's existing attachments left as-is.

**Architecture:** One polymorphic `document_attachments` table and one `attachments` blueprint (`app/attachments/`), keyed by `(document_type, document_id)` exactly like `DocumentRevision`. A registry describes each document type (loader, open statuses, roles, amendment predicate). Modules plug in with one Jinja global call and one include on their detail/form pages, plus a one-line hook in their create routes.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, SQLite, Alembic (hand-written migration), Jinja2, pytest.

Spec: `docs/design/2026-09-15-document-attachments-design.md`.

## Global Constraints

- Never `datetime.now()`; use `ph_now` from `app.utils`.
- Migration is hand-written; new table only; FK named inline: `fk_document_attachments_uploaded_by`.
- Head to revise: `f179afe2918a`.
- Audit through `app.audit.utils.log_create` / `log_delete`; audit module name `<document_type>_attachment`.
- Allowlist and SVG exclusion copied from `app/accounts_payable/views.py:506-519`.
- Absence assertions in tests target the form `action=` attribute, not a class name.
- Register the `attachments` marker in `pytest.ini`.
- CDV audit module for the document itself is `cash_disbursement`; the attachment module is `cash_disbursements_attachment` (document_type-based).
- Do not touch `app/accounts_payable/*` except nothing — AP is out of scope.
- Do not create tooling files inside `cas/` (`CLAUDE.md`, `.claude/`).

---

## File structure

Create:
- `app/attachments/__init__.py` — blueprint object `attachments_bp`, `init_app`-style registration helpers.
- `app/attachments/models.py` — `DocumentAttachment`.
- `app/attachments/registry.py` — `AttachmentTarget`, `TARGETS`, `get_target()`, `can_upload()`, `can_delete()`.
- `app/attachments/service.py` — `ALLOWED_TYPES`, `file_path()`, `save_attachment()`, `save_queued_attachments()`, `delete_attachment()`, `attachments_for()`, `panel_context()`.
- `app/attachments/views.py` — upload / download / preview / delete routes and the `attachment_panel` Jinja global.
- `app/attachments/templates/attachments/_panel.html` — shared panel partial.
- `app/attachments/templates/attachments/_create_queue.html` — create-form queue partial.
- `app/static/js/attachment_queue.js` — shared queue script.
- `migrations/versions/docatt_0001_document_attachments.py`.
- `tests/unit/test_attachment_gates.py`.
- `tests/integration/test_document_attachments.py`.

Modify:
- `app/__init__.py` — register blueprint, import model for Alembic, create upload dirs.
- `pytest.ini` — `attachments` marker.
- `app/purchase_requests/views.py` (create), `app/purchase_orders/views.py` (create), `app/receiving_reports/views.py` (create), `app/cash_disbursements/views.py` (create) — save queued files after commit.
- The four `detail.html` and `form.html` templates — include the panel / queue; add `enctype` to the create form.

---

### Task 1: Model + migration + registry + gate unit tests

**Files:**
- Create: `app/attachments/__init__.py`, `app/attachments/models.py`, `app/attachments/registry.py`, `migrations/versions/docatt_0001_document_attachments.py`, `tests/unit/test_attachment_gates.py`
- Modify: `app/__init__.py` (model import near line 267; blueprint registration near line 376; makedirs near line 221), `pytest.ini` (marker)

**Interfaces produced:**
```python
class DocumentAttachment(db.Model):  # table document_attachments
    id, document_type, document_id, original_filename, stored_filename, mime_type,
    file_size, uploaded_by_id, uploaded_by, uploaded_at
    is_image -> bool ; file_size_human -> str

@dataclass(frozen=True)
class AttachmentTarget:
    document_type: str; model_path: str; number_attr: str; view_endpoint: str
    open_statuses: tuple; edit_roles: tuple; amend_statuses: tuple = ()
    amend_level: callable | None = None      # (user) -> bool
    def load(self, document_id) -> doc | None
    def number(self, doc) -> str

TARGETS: dict[str, AttachmentTarget]
get_target(document_type) -> AttachmentTarget | None
can_upload(target, doc, user) -> bool
can_delete(target, doc, user, attachment) -> bool
```

- [ ] Step 1: write `tests/unit/test_attachment_gates.py` with a `SimpleNamespace` user/doc and assert the status/role table from the spec (PR staff draft → True; PR staff approved → False; PR accountant approved → True; PO staff submitted → True; RR staff billed → False; CDV staff posted → False; delete: uploader True, other staff False, accountant True).
- [ ] Step 2: run, expect ImportError.
- [ ] Step 3: implement registry, model, migration, wiring.
- [ ] Step 4: run unit test → PASS. Upgrade a **copy** of `instance/philgen.db` with the migration and confirm `document_attachments` exists with the index and FK.
- [ ] Step 5: commit `feat(attachments): shared document_attachments table, registry and gates`.

### Task 2: Service + routes + integration tests

**Files:**
- Create: `app/attachments/service.py`, `app/attachments/views.py`, `tests/integration/test_document_attachments.py`

**Interfaces produced:**
```python
ALLOWED_TYPES: dict[str, str]                       # '.png' -> 'image/png'
file_path(attachment) -> str
save_attachment(target, doc, file_storage, user) -> tuple[bool, str | None]
save_queued_attachments(target, doc, files, user) -> list[str]   # skipped filenames
delete_attachment(target, doc, attachment, user) -> None
attachments_for(document_type, document_id) -> list[DocumentAttachment]
panel_context(document_type, doc, user, next_url=None) -> dict
# Jinja global: attachment_panel(document_type, doc, next_url=None) -> dict (same as panel_context for current_user)
# Routes: attachments.upload(document_type, document_id) POST
#         attachments.download(attachment_id) GET
#         attachments.preview(attachment_id) GET
#         attachments.delete(attachment_id) POST
```

- [ ] Step 1: write integration tests (factories for a draft PR/PO/RR/CDV in `main_branch`; login helper; `sess['selected_branch_id']`): upload creates row+file+audit; refused when approved/posted (302 + no row); PR/PO accountant upload while approved OK, staff refused; bad extension refused; download headers; preview 404 for pdf; delete matrix; unknown type 404.
- [ ] Step 2: run → fail (404s / ImportError).
- [ ] Step 3: implement service and views; register blueprint (done in Task 1 wiring) and Jinja global.
- [ ] Step 4: run → PASS.
- [ ] Step 5: commit `feat(attachments): upload/download/preview/delete routes with audit`.

### Task 3: Templates — panel, create queue, module wiring

**Files:**
- Create: `app/attachments/templates/attachments/_panel.html`, `app/attachments/templates/attachments/_create_queue.html`, `app/static/js/attachment_queue.js`
- Modify: `app/purchase_requests/templates/purchase_requests/{detail,form}.html`, `app/purchase_orders/templates/purchase_orders/{detail,form}.html`, `app/receiving_reports/templates/receiving_reports/{detail,form}.html`, `app/cash_disbursements/templates/cash_disbursements/{detail,form}.html`
- Modify create routes: `app/purchase_requests/views.py:~386`, `app/purchase_orders/views.py:~605`, `app/receiving_reports/views.py:~806`, `app/cash_disbursements/views.py:~975`
- Test: extend `tests/integration/test_document_attachments.py` with: detail page of a draft shows the upload form action; approved shows none; create POST with `attachments` files attaches them.

Panel usage on a detail page (after the line-items card, outside any form):
```jinja
{% set att = attachment_panel('purchase_requests', pr) %}
{% include 'attachments/_panel.html' %}
```
Form pages: same include after `</form>` when the doc exists (edit or amend); in create mode, `{% include 'attachments/_create_queue.html' %}` inside the form and `enctype="multipart/form-data"` on the `<form>` tag, plus `<script src="{{ url_for('static', filename='js/attachment_queue.js') }}?v=1"></script>`.

Create route hook (each module, right after its `log_create(...)`, before the success flash):
```python
from app.attachments.service import save_queued_attachments
from app.attachments.registry import get_target
skipped = save_queued_attachments(get_target('purchase_requests'), pr,
                                  request.files.getlist('attachments'), current_user)
if skipped:
    flash('Some files were not attached and were skipped: ' + ', '.join(skipped), 'warning')
```

- [ ] Steps: write tests → fail → implement → pass → commit `feat(attachments): panels on PR/PO/RR/CDV pages and create-form queue`.

### Task 4: Verification in the running app (owner's finish line)

- [ ] Restart philgen (`.\cas.ps1 philgen`, port 5050).
- [ ] With the Chrome MCP, for each of PR, PO, RR, AP, CV: open or create a draft, upload a PNG and a PDF, confirm both are listed, open the image preview, and confirm an approved/posted document shows no upload form. Record the outcome per document in the final report.
- [ ] Run `pytest tests/integration/test_document_attachments.py tests/unit/test_attachment_gates.py tests/integration/test_accounts_payable_attachments.py tests/unit/test_markexpr_guard.py -q` and the four module marker suites.
