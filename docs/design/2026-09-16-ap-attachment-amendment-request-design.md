# AP attachment amendment request — specification

Date: 2026-09-16. Builds on the required/labeled attachments feature (spec
`2026-09-15-required-labeled-attachments-spec.md`, shipped and deployed at
migration `reqatt_0001`). Follows the established request/approve precedent
`PurchaseRequestAmendmentRequest` (`app/purchase_requests/amendment_models.py`,
table `pr_amendment_requests`).

## At a glance

- A posted **AP Voucher** can be approved (posted) with its required **Signed AP**
  still missing — the soft gate allows it and the detail page shows an
  **Incomplete** badge. Today that badge can never be cleared through the UI: AP's
  attachment uploader is gated to `status == 'draft'`, and AP has no amendment path.
- This adds a **narrow, attachments-only amendment request** for AP: an edit-level
  user attaches the missing required file to a **request**, an approver reviews and
  **approves**, and only then is the file committed onto the posted AP — clearing
  the badge. Nothing financial changes, ever.
- Mechanism decisions (from design): **request → approve → upload**, and the
  **file rides with the request** (staged off-document, committed atomically on
  approval). AP-specific model mirroring the PR precedent.

## Problem & goal

The required/labeled feature made "Signed AP" a required slot and added a soft gate
at posting: an AP posted without its signed copy is allowed through, snapshotted in
`approved_incomplete_slots`, and flagged with an **Incomplete** badge. RR, CV, PR and
PO can complete such a document after approval (RR/CV by an approver uploading
directly; PR/PO through their amend path). **AP cannot** — it keeps a separate
attachment subsystem (`accounts_payable_attachments`, `_save_ap_attachment`, its own
detail-page UI) whose upload path refuses once `status != 'draft'`, and AP has no
amendment workflow. So a posted-incomplete AP is stuck flagged.

**Goal:** let the missing required file reach a posted AP through a controlled
request/approve cycle that never touches posted financial content, honouring BIR
permanence.

**Non-goals:** any change to AP amounts, VAT/WHT, or the journal entry; a general AP
amendment (financial corrections remain the separately-deferred, BIR-reviewed work);
extending the request cycle to RR/CV/PR/PO (they already complete without it).

## Design

### 1. Data model

New model `AccountsPayableAmendmentRequest` (`app/accounts_payable/amendment_models.py`),
table `ap_amendment_requests`, mirroring `PurchaseRequestAmendmentRequest`:

| Column | Notes |
|---|---|
| `id` | PK |
| `ap_id` | FK `accounts_payable.id`, indexed |
| `branch_id` | FK `branches.id`, indexed — branch-scoped from day one (branch-scoping rule) |
| `requested_by_id` | FK `users.id` |
| `reason` | Text; `MIN_REASON_LEN = 10`, enforced in form + service (field error, not 500) |
| `kind` | slot key being filled (always `signed_ap` today; column keeps it general) |
| `staged_original_filename`, `staged_stored_filename`, `staged_mime_type`, `staged_file_size` | the file staged with the request |
| `status` | `pending` / `approved` / `rejected` / `withdrawn`, indexed |
| `reviewed_by_id`, `reviewed_at`, `review_note` | approver action |
| `created_at`, `updated_at` | `ph_now()` |
| `RowVersioned` | approve/reject is a lost-update pair (two approvers acting a moment apart must not both commit) |

Index `ix_ap_amend_req_pending (ap_id, status)`, as PR does. Migration is hand-written
(`create_table`, named FK constraints, no batch wrapper), verified against a copy of a
real database.

### 2. Request lifecycle & states

```
posted AP, Incomplete (missing signed_ap)
        │  edit-level user: attach file + reason
        ▼
     pending ──(requester)── withdrawn         (staged file deleted)
        │
        ├─(approver) reject ── rejected         (staged file deleted; review_note kept)
        │
        └─(approver) approve ─ approved
                 └─ commit: staged file → accounts_payable_attachments row (kind=signed_ap),
                    audited as an attachment revision; badge self-heals.
```

- **Only one** open (`pending`) request per AP at a time (the pending index supports the
  guard; a second request while one is pending is refused with a flash).
- A request may be opened only on an AP that is **posted (or later)** and **currently
  Incomplete** for that slot — i.e. `missing_required('accounts_payable', ap)` includes
  the slot. If the slot is already filled, there is nothing to request.
- Approve is idempotent-safe via `RowVersioned`; on a stale version it re-reads and the
  second approver sees "already handled".

### 3. File staging

The staged file lives under `instance/uploads/ap_amendment_requests/<request_id>/<stored>`
while `pending`. It is **never** on the AP until approval.

- **On approve:** validate the slot is still empty (re-check at commit — the authoritative
  pattern from the soft gate); move/copy the file into the AP's folder
  (`instance/uploads/accounts_payable/<ap_id>/`); create the `accounts_payable_attachments`
  row with `kind`, `uploaded_by_id = requester`; write the audit revision; delete the staged
  copy; set `status='approved'`, `reviewed_by/at`. All in one transaction.
- **On reject / withdraw:** delete the staged file; set the terminal status.
- File validation (extension allowlist, size) happens at **request** time, reusing the AP
  attachment validator so a bad file is rejected before it is staged.

### 4. Surfacing

- **AP detail page** (`accounts_payable/detail.html`): when the AP is posted and Incomplete —
  - edit-level users with no pending request see **"Request amendment to attach Signed AP"**
    (file input + reason);
  - a pending request shows its status and, for the requester, a **Withdraw** control;
  - approvers see the staged file (preview/download) with **Approve** / **Reject**.
- **Action Items** (`gather_approval_items`): a `pending` AP amendment request appears in the
  **For Approval** panel for approvers, exactly as PR amendment requests do — description
  e.g. *"AP amendment: attach Signed AP"*, a Review link to the AP. Counted in the badge the
  same way PR amendment requests are.
- The existing **Incomplete badge** needs no change — it is computed from
  `approved_incomplete_slots ∩ still-missing`, so it clears itself once the file lands.

### 5. Permissions

- **Request / withdraw:** edit-level (`EDIT_ROLES`), and (for withdraw) the original requester.
- **Approve / reject:** approve-level (`_approve_level` — accountant or full access), matching
  the AP posting gate, so no one who cannot post an AP can complete an approved one.
- Everything **branch-scoped**: lists and lookups filter by `branch_id`, per the branch rule.

### 6. Edge cases

- **AP voided/cancelled after a request is opened:** the request is stale; approve re-checks AP
  status and slot, and refuses with a flash rather than attaching to a dead voucher; the request
  is auto-withdrawn.
- **Slot filled by another path before approval** (e.g. the AP was voided-and-reissued): the
  commit-time re-check finds the slot non-empty and refuses; request marked `rejected` with a
  note "already completed".
- **Config change** (Signed AP later made not-required): the badge is frozen at posting
  (snapshot), so it can still show Incomplete; a request is still allowed to clear it. Filling
  the slot always clears the badge regardless of current config.
- **`log_audit` swallow caveat:** the attachment row + request status are written in the business
  transaction, not via the audit log, so a failed audit write never loses the attachment.

## Decisions Log

| ID | Topic | Decision | Rationale | Source |
|---|---|---|---|---|
| A1 | AP completion mechanism | Request → approve → upload (attachments only) | Owner wants a "user asks" step; AP has no direct approver-upload path | Interview 2026-09-16 |
| A2 | How the file arrives | File rides with the request; committed atomically on approve | Nothing on the posted AP changes until approval — safest for BIR permanence | Interview 2026-09-16 |
| A3 | Model shape | AP-specific `AccountsPayableAmendmentRequest`, mirroring `PurchaseRequestAmendmentRequest` | Only AP needs a request cycle; follows an established precedent; YAGNI vs a generic table | Interview 2026-09-16 |
| A4 | Actors | Request/withdraw: edit-level (+requester); approve/reject: approve-level | Mirrors AP posting gate and the PR "ask without write" seam | Interview 2026-09-16 |
| A5 | Scope | Attachments only; no amount/VAT/WHT/JE change | Financial AP amendment stays the separately-deferred, BIR-reviewed work | Interview + prior spec D11 |
| A6 | Commit safety | Re-check slot-empty and AP status at approve time | The soft gate's authoritative-server pattern; guards races and stale requests | Design |
| A7 | Concurrency | `RowVersioned` on the request | Approve/reject is a lost-update pair, as on the PR model | Precedent |

## Dependency Graph & Implementation Order

```
1. Data model + migration      → ap_amendment_requests table (create_table, named FKs);
                                  AccountsPayableAmendmentRequest model
2. Service                     → request(create+stage file), withdraw, approve(commit+audit),
   (depends on 1)               reject; commit-time re-checks; reuse _save_ap_attachment path
3. Routes                      → POST request / withdraw / approve / reject on the AP module,
   (depends on 2)               branch-scoped, gated (edit vs approve level)
4. Detail-page UI              → request control (posted+incomplete), pending status + withdraw,
   (depends on 3)               approver review (staged-file preview + Approve/Reject)
5. Action Items                → pending AP amendment requests in For Approval + badge count
   (depends on 2)
6. Tests                       → model/migration; service (stage→approve commits row, reject/
   (depends on all)             withdraw discard, re-check refusals); route gating; badge self-heal
```

Build 1 → 2 → 3, then 4/5 (each depends on 2/3), then 6 throughout (TDD per unit).
Each step is independently testable; there is no financial-path change at any step.
