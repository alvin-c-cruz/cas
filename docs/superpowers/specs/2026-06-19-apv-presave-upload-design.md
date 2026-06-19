# APV pre-save file upload — design

**Date:** 2026-06-19
**Status:** Approved (design)
**Feature:** Allow attaching files on the Accounts Payable Voucher (APV) **create** form, before the voucher is first saved as a draft.

## Problem

Today the Attachments section in `app/accounts_payable/templates/accounts_payable/form.html` is wrapped in `{% if ap %}`, so it renders only when editing a **saved** APV. The upload route is `/<id>/attachments/upload` and `AccountsPayableAttachment.ap_id` is `nullable=False`, so attachments are keyed to a saved AP id both in the DB and on disk (`instance/uploads/accounts_payable/<ap_id>/`). On the create form there is no record yet, so a user cannot attach supporting documents until after the first save. Users want to attach files while entering a brand-new voucher.

This is not a regression — the create form never had an upload control. This is a new, additive feature.

## Chosen approach

**Hold files in the browser, persist on Save, allow multiple files.**

- Files are *selected* on the create form but **not uploaded** to the server until the user clicks Save.
- On a successful create POST, the APV row is created first (so `ap.id` exists), then each uploaded file is saved as an `AccountsPayableAttachment` exactly as edit-mode upload does today.
- **No model change. No staging area. No orphan-file cleanup.** Attachments only ever become rows/files after a real `ap.id` exists.

### Approaches considered (and why rejected)

1. **Immediate upload into a staging area** keyed by a temp token, moved to the real AP on save. Survives validation bounces and supports pre-save preview, but requires a staging store, a model change (nullable `ap_id` or a staging token), and an orphan-reaper. Rejected as over-built for the need (YAGNI).
2. **Auto-create a draft on first attach.** Reuses existing infra but consumes AP numbers and clutters the books with partial drafts. Rejected.
3. **Hold-in-browser, persist on save (chosen).** Simplest; zero schema/storage changes. Single known limitation: a server-side validation bounce clears the browser's file inputs, so the queued files must be re-selected (see Limitation).

## Backend changes

All in `app/accounts_payable/views.py`.

1. **Extract a shared helper** from the existing `upload_attachment()`:

   ```
   _save_ap_attachment(ap, file_storage, user) -> (ok: bool, error: str | None)
   ```

   It performs the **identical** steps already in `upload_attachment()`:
   - `secure_filename(file_storage.filename)`; reject empty/invalid names.
   - Extension allow-list check against `_ATTACHMENT_ALLOWED` (SVG intentionally excluded). On a disallowed type, return `(False, "<message>")` — do **not** raise.
   - `stored_name = uuid4().hex + ext`; save to `_ap_upload_dir(ap.id)`.
   - Create `AccountsPayableAttachment(ap_id=ap.id, original_filename, stored_filename, mime_type, file_size, uploaded_by_id=user.id)`.
   - `log_create(module='accounts_payable_attachment', ...)` audit row.
   - **Commit this attachment atomically** (file + row + audit), mirroring today's edit-mode upload. On any exception: roll back and remove the saved file (if written), then return `(False, "<generic message>")`.

   Each attachment is its own atomic unit. This deliberately avoids deferring a single commit across N file writes, which would orphan already-written files on disk if a later commit failed.

2. **Refactor `upload_attachment()` (edit mode)** to call the helper for its single file. Externally observable behavior is unchanged.

3. **`create()`**: the APV is validated, created, and **committed first, exactly as today** (this ordering is unchanged). *Then*, once `ap.id` is committed, loop `request.files.getlist('attachments')`:
   - Skip empty file slots (no filename).
   - For each file, call `_save_ap_attachment(ap, f, current_user)` (which commits that attachment).
   - **Open-point resolution (option a):** keep the APV and all valid files; collect the names of any files skipped due to a bad type/error and flash a warning listing them. A bad file never blocks the voucher or the other files.
   - Because attachments are processed only after the APV commit, an AP that fails validation writes **no** files to disk (see Limitation), and a failure on one attachment never orphans another.

   Audit: each attachment logs its own `log_create` (via the helper). The APV's own create audit is unchanged.

## Frontend changes

All in `app/accounts_payable/templates/accounts_payable/form.html` (create branch) and its inline script.

4. Add `enctype="multipart/form-data"` to the create form's `<form>` (it is not multipart today because it has no file inputs).
5. Add an **Attachments card** rendered on the create form (i.e. also when `ap` is None). It contains:
   - `<input type="file" name="attachments" multiple accept="<same list as edit mode>">`.
   - A JS-rendered **queued-file list**: filename + human size + a "remove" (✕) control that drops a file from the selection before saving. Implemented by maintaining a `DataTransfer`-backed `FileList` (or an array mirrored into the input) so removals are reflected in what submits.
   - Helper text noting files attach when the voucher is saved.
6. **Client-side type pre-check** mirroring `_ATTACHMENT_ALLOWED`: warn on a disallowed extension at selection time. This is convenience only; the server re-validates authoritatively.
7. Design tokens / existing card styling only — no hardcoded styling. Responsive, consistent with the existing edit-mode Attachments card.

The existing edit-mode Attachments block (`{% if ap %}` … upload/list/preview/delete) is **unchanged**. The new create-mode card is a separate, simpler block shown when there is no `ap`.

## Limitation (accepted)

If the create POST fails **server-side** validation and the form re-renders, browsers clear file inputs for security, so the queued files are lost and must be re-selected. Mitigations:
- The existing client-side `validateForm()` already gates the submit button on required fields, so server-side bounces are rare.
- On a re-render after a bounce, flash a clear notice: *"Your attached files were cleared — please re-attach before saving."*
- Line items continue to be restored via `restore_lines` exactly as today.

Avoiding this entirely would require the staging approach, which was considered and rejected.

## What does NOT change

- **Model / migration:** none. `AccountsPayableAttachment.ap_id` stays `nullable=False`.
- **Edit-mode upload, download, preview, delete, and void cleanup:** unchanged.
- **Permissions:** `create()` already restricts to accountant/admin; reused. No new endpoint.
- **File size limit:** reuse the existing `MAX_CONTENT_LENGTH` behavior.

## Ripple-effect review

- **Views:** `create()` (new file loop), `upload_attachment()` (refactor to helper). No other route touched.
- **Templates:** `form.html` create branch (new card + multipart enctype + queued-list JS). `detail.html` unchanged.
- **Model / migration / cache / reports / exports / `to_dict`:** unaffected.
- **Void logic:** already deletes attachments by walking `ap.attachments` + disk path; works unchanged for attachments created at create-time.
- **Audit:** one `log_create` per attachment (existing pattern), plus the unchanged APV create audit.

## Testing

Integration (`tests/integration/`):
- `create()` POST with 2 valid files → APV created, 2 `AccountsPayableAttachment` rows, 2 attachment audit rows + the APV create audit.
- `create()` POST mixing 1 valid + 1 disallowed type (e.g. `.svg`) → APV saved, the valid file attached, the bad file skipped, warning flash names it (option a).
- `create()` POST with no files → behaves exactly as today (no attachments, no error).
- `create()` POST whose line items fail validation **plus** files attached → APV not created, no attachment rows, no files written to disk (verifies files are only persisted after AP creation).
- Edit-mode `upload_attachment()` still creates an attachment + audit row (refactor regression guard).

Each write asserts the matching audit entry, per project convention.

## Out of scope

- Attaching files to **posted** vouchers (separate enhancement; today attachments are draft-only).
- Pre-save server-side staging / preview of files before the voucher is saved.
- Drag-and-drop upload UX.
