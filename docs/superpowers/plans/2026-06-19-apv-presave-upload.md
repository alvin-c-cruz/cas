# APV Pre-Save File Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users attach multiple files on the APV *create* form before the voucher is first saved; the files persist as attachments when the voucher is saved.

**Architecture:** Files are held in the browser and submitted with the create POST (multipart). `create()` creates and commits the APV first (unchanged), then persists each uploaded file via a shared `_save_ap_attachment` helper extracted from the existing edit-mode upload. No model, migration, or staging changes.

**Tech Stack:** Flask, SQLAlchemy, Jinja2, Werkzeug file uploads, pytest (Flask test client), vanilla JS (Choices.js already present, not needed here).

## Global Constraints

- **No model or migration change.** `AccountsPayableAttachment.ap_id` stays `nullable=False`.
- **Reuse the existing allow-list** `_ATTACHMENT_ALLOWED` in `app/accounts_payable/views.py` (SVG intentionally excluded). Accept list string (HTML `accept` + client JS): `.png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt`.
- **Audit every attachment** via `log_create(module='accounts_payable_attachment', ...)` — already done inside the helper.
- **Option (a):** a file with a disallowed type/error is skipped with a warning; it never blocks the voucher or the other files.
- **No JS popups** (`confirm`/`alert`/`prompt`); custom HTML only. **Design tokens only**, responsive.
- **Submit button copy unchanged** ("Save"/"Update").
- **Verify the audit log in CRUD tests** — after each write assert the audit row.
- Commit after each task.

---

## File Structure

- `app/accounts_payable/views.py` — add `_save_ap_attachment` helper; refactor `upload_attachment()`; extend `create()` (file loop + bounce warning).
- `app/accounts_payable/templates/accounts_payable/form.html` — add `enctype` to `#billForm`; add a create-mode Attachments card inside the form; add queued-list JS + client-side type pre-check.
- `tests/integration/test_accounts_payable_attachments.py` — **new** test file for the helper/edit-upload regression and the create-with-files behavior.
- `tests/integration/test_accounts_payable_views.py` — add a render assertion for the create-mode upload control.

---

## Task 1: Extract `_save_ap_attachment` helper + refactor edit-mode upload

**Files:**
- Modify: `app/accounts_payable/views.py` (add helper after `_ATTACHMENT_ALLOWED` at line 323; refactor `upload_attachment()` at lines 1209–1277)
- Test: `tests/integration/test_accounts_payable_attachments.py` (create)

**Interfaces:**
- Produces: `_save_ap_attachment(ap, file_storage, user) -> tuple[bool, str | None]`
  - Saves `file_storage` to `_ap_upload_dir(ap.id)`, creates an `AccountsPayableAttachment`, writes a `log_create` audit row, and **commits that attachment atomically**.
  - Returns `(True, None)` on success; `(False, "<message>")` on a disallowed type / invalid name / error (after rolling back and removing any written file). Never raises for those cases.

- [ ] **Step 1: Write the regression test for edit-mode upload (characterizes current behavior; must pass before and after the refactor)**

Create `tests/integration/test_accounts_payable_attachments.py`:

```python
"""Integration tests for APV file attachments (edit-mode upload + create-form upload)."""
import io
import json
from datetime import date
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayable, AccountsPayableAttachment
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor
from app.audit.models import AuditLog

pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='ATV001', name='Attach Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True,
               payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def make_draft_ap(db_session, vendor, branch, ap_number='ATT-DRAFT-1'):
    ap = AccountsPayable(
        ap_number=ap_number, vendor_id=vendor.id, vendor_name=vendor.name,
        vendor_tin='', vendor_address='', branch_id=branch.id,
        ap_date=date.today(), due_date=date.today(), status='draft',
        subtotal=Decimal('100.00'), vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('100.00'), withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'), total_amount=Decimal('100.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('100.00'),
        payment_terms='Net 30',
    )
    db_session.add(ap)
    db_session.commit()
    return ap


def test_edit_mode_upload_creates_attachment_and_audit(client, db_session, admin_user, main_branch):
    login(client)
    vendor = make_vendor(db_session)
    ap = make_draft_ap(db_session, vendor, main_branch)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post(
        f'/accounts-payable/{ap.id}/attachments/upload',
        data={'attachment': (io.BytesIO(b'%PDF-1.4 test'), 'invoice.pdf')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200

    atts = AccountsPayableAttachment.query.filter_by(ap_id=ap.id).all()
    assert len(atts) == 1
    assert atts[0].original_filename == 'invoice.pdf'
    assert atts[0].mime_type == 'application/pdf'

    audit = AuditLog.query.filter_by(module='accounts_payable_attachment', action='create').all()
    assert len(audit) == 1
```

- [ ] **Step 2: Run the test to verify it passes against current code**

Run: `python -m pytest tests/integration/test_accounts_payable_attachments.py::test_edit_mode_upload_creates_attachment_and_audit -q --no-cov`
Expected: PASS (this characterizes existing behavior before refactor).

> If it fails on the audit assertion, inspect the actual `AuditLog` rows for the correct `module`/`action` values and adjust the assertion to match current behavior before continuing — do not change app code in this step.

- [ ] **Step 3: Add the `_save_ap_attachment` helper**

In `app/accounts_payable/views.py`, immediately after the `_ATTACHMENT_ALLOWED` dict (ends at line 323), add:

```python
def _save_ap_attachment(ap, file_storage, user):
    """Validate and persist one uploaded file as an AccountsPayableAttachment.

    Saves to _ap_upload_dir(ap.id), creates the DB row, writes an audit entry,
    and commits this attachment atomically (mirrors edit-mode upload). Returns
    (True, None) on success or (False, message) on a disallowed type / invalid
    name / error — after rolling back and removing any written file. Never
    raises for those cases, so a bad file can be skipped by the caller.
    """
    original_name = secure_filename(file_storage.filename or '')
    if not original_name:
        return False, 'Invalid filename.'

    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    mime_type = _ATTACHMENT_ALLOWED.get(ext)
    if mime_type is None:
        allowed = ', '.join(sorted(_ATTACHMENT_ALLOWED))
        return False, f'File type "{ext or "unknown"}" is not allowed. Accepted: {allowed}'

    stored_name = uuid.uuid4().hex + ext
    file_path = os.path.join(_ap_upload_dir(ap.id), stored_name)
    try:
        file_storage.save(file_path)
        file_size = os.path.getsize(file_path)

        attachment = AccountsPayableAttachment(
            ap_id=ap.id,
            original_filename=original_name,
            stored_filename=stored_name,
            mime_type=mime_type,
            file_size=file_size,
            uploaded_by_id=user.id,
        )
        db.session.add(attachment)
        db.session.commit()

        log_create(
            module='accounts_payable_attachment',
            record_id=attachment.id,
            record_identifier=f'{ap.ap_number} / {original_name}',
            new_values={
                'ap_id': ap.id,
                'original_filename': original_name,
                'stored_filename': stored_name,
                'mime_type': mime_type,
                'file_size': file_size,
            },
        )
        return True, None
    except Exception:
        db.session.rollback()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        current_app.logger.error('Error saving AP attachment', exc_info=True)
        return False, 'An unexpected error occurred while saving the file.'
```

- [ ] **Step 4: Refactor `upload_attachment()` to use the helper**

Replace the body of `upload_attachment()` (lines 1209–1277) below the draft-status guard with a call to the helper. The function becomes:

```python
def upload_attachment(id):
    """Upload a file attachment to a draft AP Voucher (edit mode)."""
    ap = _get_ap_or_404(id)

    if ap.status != 'draft':
        flash('Attachments can only be uploaded while the APV is in draft status.', 'error')
        return redirect(url_for('accounts_payable.edit', id=id))

    uploaded_file = request.files.get('attachment')
    if not uploaded_file or uploaded_file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('accounts_payable.edit', id=id))

    ok, err = _save_ap_attachment(ap, uploaded_file, current_user)
    if ok:
        flash(f'File "{secure_filename(uploaded_file.filename)}" uploaded successfully.', 'success')
    else:
        flash(err, 'error')

    return redirect(url_for('accounts_payable.edit', id=id))
```

- [ ] **Step 5: Run the regression test — still passes**

Run: `python -m pytest tests/integration/test_accounts_payable_attachments.py::test_edit_mode_upload_creates_attachment_and_audit -q --no-cov`
Expected: PASS (behavior unchanged after refactor).

- [ ] **Step 6: Commit**

```bash
git add app/accounts_payable/views.py tests/integration/test_accounts_payable_attachments.py
git commit -m "refactor(apv): extract _save_ap_attachment helper from upload_attachment"
```

---

## Task 2: `create()` persists queued files after the APV commit (option a)

**Files:**
- Modify: `app/accounts_payable/views.py` `create()` (lines 507–627)
- Test: `tests/integration/test_accounts_payable_attachments.py` (append)

**Interfaces:**
- Consumes: `_save_ap_attachment(ap, file_storage, user)` from Task 1.
- Produces: `create()` reads `request.files.getlist('attachments')` and persists each valid file after the APV is committed; skipped files are flashed as a warning.

- [ ] **Step 1: Write the failing test — create POST with one valid file attaches it**

Append to `tests/integration/test_accounts_payable_attachments.py`:

```python
def _seed_je_accounts(db_session):
    """Structural accounts + a VAT category required for a successful create POST."""
    def goc(code, name, atype):
        a = Account.query.filter_by(code=code).first()
        if not a:
            a = Account(code=code, name=name, account_type=atype, is_active=True)
            db_session.add(a)
            db_session.commit()
        return a

    goc('20101', 'Accounts Payable - Trade', 'Liability')
    vat_acct = goc('10501', 'Input VAT - Current', 'Asset')
    exp = goc('61001', 'Rent Expense', 'Expense')
    vat_cat = VATCategory.query.filter_by(code='VAT12').first()
    if not vat_cat:
        vat_cat = VATCategory(code='VAT12', name='VAT 12%', rate=Decimal('12'),
                              is_active=True, input_vat_account_id=vat_acct.id)
        db_session.add(vat_cat)
        db_session.commit()
    return exp


def _line_items(account_id):
    return json.dumps([{
        'description': 'Test Service', 'amount': 11200.00,
        'vat_category': 'VAT12', 'account_id': account_id,
        'wt_id': None, 'wt_rate': None,
    }])


def _create_payload(vendor, account_id, files):
    data = {
        'ap_number': 'PRESAVE-1',
        'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'vendor_id': vendor.id,
        'payment_terms': 'Net 30',
        'notes': 'Test particulars',
        'line_items': _line_items(account_id),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }
    if files is not None:
        data['attachments'] = files
    return data


def test_create_with_one_file_attaches_it(client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    vendor = make_vendor(db_session, code='PSV001')
    exp = _seed_je_accounts(db_session)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post(
        '/accounts-payable/create',
        data=_create_payload(vendor, exp.id,
                             [(io.BytesIO(b'%PDF-1.4 a'), 'receipt.pdf')]),
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200

    ap = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
    assert ap is not None
    atts = AccountsPayableAttachment.query.filter_by(ap_id=ap.id).all()
    assert len(atts) == 1
    assert atts[0].original_filename == 'receipt.pdf'

    audit = AuditLog.query.filter_by(module='accounts_payable_attachment', action='create').count()
    assert audit == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/integration/test_accounts_payable_attachments.py::test_create_with_one_file_attaches_it -q --no-cov`
Expected: FAIL — `assert len(atts) == 1` fails with `0` (create() ignores files).

- [ ] **Step 3: Implement the file loop in `create()`**

In `app/accounts_payable/views.py`, inside `create()`, between the `log_create(...)` call (ends line 595) and the success `flash(...)` (line 597), insert:

```python
            # Persist files queued on the create form (held in the browser until
            # Save). The APV is already committed, so ap.id is stable; each file
            # commits atomically. Option (a): a bad file is skipped with a
            # warning and never blocks the voucher or the other files.
            skipped = []
            for f in request.files.getlist('attachments'):
                if not f or not f.filename:
                    continue
                ok, err = _save_ap_attachment(ap, f, current_user)
                if not ok:
                    skipped.append(f.filename)
            if skipped:
                flash('Some files were not attached and were skipped: '
                      + ', '.join(skipped), 'warning')
```

Then add the bounce warning at the **top of the nested `_render_form` function** (right after its docstring, before the `vat_categories = ...` line at 521):

```python
        if request.method == 'POST' and any(
                f and f.filename for f in request.files.getlist('attachments')):
            flash('Your attached files were cleared — please re-attach before saving.', 'warning')
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_accounts_payable_attachments.py::test_create_with_one_file_attaches_it -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Add option-(a) and edge-case tests**

Append:

```python
def test_create_mixed_valid_and_bad_type_saves_valid_and_skips_bad(
        client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    vendor = make_vendor(db_session, code='PSV002')
    exp = _seed_je_accounts(db_session)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post(
        '/accounts-payable/create',
        data=_create_payload(vendor, exp.id, [
            (io.BytesIO(b'%PDF-1.4 ok'), 'good.pdf'),
            (io.BytesIO(b'<svg></svg>'), 'bad.svg'),
        ]),
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200

    ap = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
    atts = AccountsPayableAttachment.query.filter_by(ap_id=ap.id).all()
    assert len(atts) == 1                      # voucher saved, valid file kept
    assert atts[0].original_filename == 'good.pdf'
    assert b'skipped' in resp.data             # warning names the bad file
    assert b'bad.svg' in resp.data


def test_create_with_no_files_still_works(client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    vendor = make_vendor(db_session, code='PSV003')
    exp = _seed_je_accounts(db_session)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post(
        '/accounts-payable/create',
        data=_create_payload(vendor, exp.id, None),
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    ap = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
    assert ap is not None
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0


def test_create_invalid_lines_with_file_persists_nothing(
        client, db_session, accountant_user, main_branch):
    login(client, 'accountant', 'accountant123')
    vendor = make_vendor(db_session, code='PSV004')
    _seed_je_accounts(db_session)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    before = AccountsPayable.query.count()
    data = _create_payload(vendor, account_id=None,
                           files=[(io.BytesIO(b'%PDF-1.4 x'), 'orphan.pdf')])
    data['line_items'] = json.dumps([])        # no lines -> validation fails
    resp = client.post('/accounts-payable/create', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert AccountsPayable.query.count() == before          # no AP created
    assert AccountsPayableAttachment.query.count() == 0     # no attachment row
```

- [ ] **Step 6: Run the full attachments test file**

Run: `python -m pytest tests/integration/test_accounts_payable_attachments.py -q --no-cov`
Expected: PASS (all tests).

> If `test_create_invalid_lines_with_file_persists_nothing` fails because an empty `line_items` is accepted, change the invalid payload to omit `line_items` entirely or set an out-of-range amount (`amount: 0`) — the goal is any server-side validation failure. Confirm the chosen payload makes `AccountsPayable.query.count()` stay flat.

- [ ] **Step 7: Commit**

```bash
git add app/accounts_payable/views.py tests/integration/test_accounts_payable_attachments.py
git commit -m "feat(apv): persist files queued on the create form when the voucher is saved"
```

---

## Task 3: Create-form Attachments card (multipart + queued-list JS)

**Files:**
- Modify: `app/accounts_payable/templates/accounts_payable/form.html` (form tag line 17; insert card before `</form>` at line 186; queued-list JS near the submit handler at line 764)
- Test: `tests/integration/test_accounts_payable_views.py` (append a render assertion)

**Interfaces:**
- Consumes: the `create()` handler from Task 2 (reads `request.files.getlist('attachments')`).
- Produces: a create-mode `<input type="file" name="attachments" multiple>` inside `#billForm`, with `enctype="multipart/form-data"` on the form.

- [ ] **Step 1: Write the failing render test**

Append to `tests/integration/test_accounts_payable_views.py` (inside the form-render test class, or as a new test using the existing `login`/fixtures):

```python
    def test_create_form_has_multipart_upload_control(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/accounts-payable/create')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'enctype="multipart/form-data"' in html
        assert 'name="attachments"' in html
        assert 'multiple' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/integration/test_accounts_payable_views.py -k multipart_upload_control -q --no-cov`
Expected: FAIL — strings not present.

- [ ] **Step 3: Add `enctype` to the create form**

In `form.html`, change line 17 from:

```html
        <form method="POST" novalidate id="billForm">
```

to:

```html
        <form method="POST" novalidate id="billForm" enctype="multipart/form-data">
```

- [ ] **Step 4: Add the create-mode Attachments card inside the form**

In `form.html`, immediately **before** the closing `</form>` tag at line 186 (after the hidden override inputs at lines 183–185), insert:

```html
            {% if not ap %}
            <!-- ── Attachments (create mode: held in browser, saved on Save) ── -->
            <div class="card" style="margin-top:16px;">
              <div class="card-body">
                <h3 style="font-size:14px; font-weight:600; color:var(--text-2); margin-bottom:8px;">
                  Attachments
                  <span style="font-weight:400; color:var(--text-3);">(optional — saved when you click Save)</span>
                </h3>
                <input type="file" id="createAttachments" name="attachments" multiple
                       accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt"
                       style="display:block; margin-bottom:8px;">
                <ul id="attachmentQueue" style="list-style:none; padding:0; margin:0; font-size:13px;"></ul>
              </div>
            </div>
            {% endif %}
```

- [ ] **Step 5: Run the render test — passes**

Run: `python -m pytest tests/integration/test_accounts_payable_views.py -k multipart_upload_control -q --no-cov`
Expected: PASS.

- [ ] **Step 6: Add the queued-list JS + client-side type pre-check**

In `form.html`, immediately after the form-submit handler block (after line 773, the closing `});` of the `billForm` submit listener), insert:

```html
<script>
// ── Create-form attachment queue (held in browser until Save) ────────────────
(function () {
    var input = document.getElementById('createAttachments');
    if (!input) return;                      // edit mode: no create-attachments input
    var list = document.getElementById('attachmentQueue');
    var ALLOWED = ['png','jpg','jpeg','gif','webp','pdf','doc','docx','xls','xlsx','csv','txt'];

    function ext(name) {
        var i = name.lastIndexOf('.');
        return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
    }
    function humanSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1048576).toFixed(1) + ' MB';
    }
    function render() {
        list.innerHTML = '';
        Array.prototype.forEach.call(input.files, function (f, idx) {
            var bad = ALLOWED.indexOf(ext(f.name)) === -1;
            var li = document.createElement('li');
            li.style.cssText = 'display:flex; align-items:center; gap:8px; padding:4px 0;'
                + (bad ? 'color:var(--danger, #c0392b);' : '');
            var label = document.createElement('span');
            label.textContent = f.name + ' (' + humanSize(f.size) + ')'
                + (bad ? ' — unsupported type, will be skipped' : '');
            var rm = document.createElement('button');
            rm.type = 'button';
            rm.className = 'btn btn-secondary';
            rm.style.cssText = 'font-size:12px; padding:2px 8px;';
            rm.textContent = 'Remove';
            rm.addEventListener('click', function () { removeAt(idx); });
            li.appendChild(label);
            li.appendChild(rm);
            list.appendChild(li);
        });
    }
    function removeAt(idx) {
        var dt = new DataTransfer();
        Array.prototype.forEach.call(input.files, function (f, i) {
            if (i !== idx) dt.items.add(f);
        });
        input.files = dt.files;              // keep the real FileList in sync for submit
        render();
    }
    input.addEventListener('change', render);
})();
</script>
```

- [ ] **Step 7: Manual verification (no automated coverage for the JS render path)**

Start the server (`python flask_app.py`) and, logged in as admin/`admin123`, open `/accounts-payable/create`:
1. Pick 2+ files → each appears in the queue list with name + size.
2. Pick a `.svg` → it shows red "unsupported type, will be skipped".
3. Click **Remove** on one → it leaves the list and is excluded from the submit.
4. Select a vendor, add one line item with an amount + account, attach a valid PDF, click **Save** → the saved APV's edit page shows the PDF under Attachments.

Confirm there are **zero console errors** during the above.

- [ ] **Step 8: Run the broader APV view/render suite for regressions**

Run: `python -m pytest tests/integration/test_accounts_payable_views.py tests/integration/test_apv_form_render.py -q --no-cov`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/accounts_payable/templates/accounts_payable/form.html tests/integration/test_accounts_payable_views.py
git commit -m "feat(apv): add create-form file upload control with browser-held queue"
```

---

## Final verification

- [ ] Run the full APV + attachment integration set:
  `python -m pytest tests/integration/test_accounts_payable_attachments.py tests/integration/test_accounts_payable_views.py tests/integration/test_accounts_payable_je.py -q --no-cov`
  Expected: PASS.
- [ ] Confirm no new failures vs. the known baseline (`project-preexisting-test-failures`).

## Out of scope (do not implement)

- Attaching files to **posted** vouchers (separate enhancement).
- Server-side staging / pre-save preview of files.
- Drag-and-drop upload UX.
