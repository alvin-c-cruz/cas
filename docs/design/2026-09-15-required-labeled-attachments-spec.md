# Required, labeled document attachments — specification

Date: 2026-09-15. Baseline commit: `65b569c3` (the shared attachments feature and create-redirect
change already on `main`). Builds directly on
`docs/design/2026-09-15-document-attachments-design.md`.

## At a glance

- Each document type gets **named attachment slots** (e.g. "Signed PR", "Vendor Quotation"),
  seeded in code. Any file not in a slot is an unlabeled **Other**.
- Company Settings lets the owner **toggle which seeded slots are required**, per company
  (philgen and ric independently). Owners cannot invent new slots or rename them.
- The attachments panel becomes a **per-slot checklist**: each slot shows attached ✓ / missing ✗
  with its own upload control, plus one "Other files" uploader.
- At **approve / post**, if a required slot is empty, a **confirm dialog** lists what is missing;
  proceeding is explicit ("Approve anyway"). The **server** re-checks and records the exception —
  the dialog is a courtesy, not the gate.
- **Pre-approval**, documents missing required files appear in a new **Action Items** category and
  drop off on approval. **Post-approval**, a document approved with required files missing carries a
  **computed "Incomplete" badge** that self-heals if the files are later added.
- **Required-ness is snapshotted at approval**, so later config changes never rewrite which past
  approvals look incomplete.
- **Retroactive:** historical approved documents are grandfathered — never flagged.

## Problem & goal

An admin cannot tell from approval status alone whether a record is backed by its required paperwork
(the signed copy, the vendor's quotation, the delivery receipt, the check). The shipped attachments
feature stores files but does not distinguish "the signed PR" from any other upload, and nothing warns
at approval that the required evidence is absent.

This feature adds (1) named, per-type attachment slots with a per-company required flag, (2) a soft
completeness check at the approval/posting gate that warns but allows proceeding, and (3) visibility
of incompleteness in Action Items (pre-approval) and via a badge (post-approval).

**Non-goals:** hard-blocking approval; post-approval editing of financial content or quantities (see
"Deferred"); retroactive evaluation of historical documents; folding AP's separate attachment table
into the shared one.

## Slots per document type

Every document requires its signed copy. Seeded defaults (owner may toggle the *required* flag except
where noted):

| Document | Slot | Default required | Notes |
|---|---|---|---|
| Purchase Requisition (PR) | Signed PR | required | |
| | Other | never | free uploads |
| Purchase Order (PO) | Signed PO | required | |
| | Vendor Quotation | required | |
| | Other | never | |
| Receiving Report (RR) | Signed RR | required | |
| | Vendor DR/SR | required | vendor delivery/sales receipt |
| | Other | never | |
| AP Voucher (AP) | Signed AP | required | |
| | Other supporting | never | |
| Cash Disbursement Voucher (CV) | Signed CV | required | |
| | Check copy | required **only when payment method is check** | conditional, see below |
| | Other | never | |

"Signed …" slots and the conditional Check-copy rule are the substance; the owner can relax any
required flag per company but cannot add or rename slots.

**CV Check-copy conditional:** the requirement is evaluated at **post time** against the CDV's payment
method as posted, and snapshotted with the approval marker. A CDV posted as cash never requires a
check copy, regardless of later data. A CDV posted by check requires one.

## Configuration

Slots and their default required flags are **seeded in code** — a per-document-type registry extending
the existing `app/attachments/registry.py` `AttachmentTarget`. Company Settings gains a screen that,
per company database, stores an **override of the required flag** for each seeded slot (and may hide a
slot). It cannot create, rename, or reorder slots, which keeps labels consistent so the required-check
is reliable.

- Storage: a settings row per (document_type, slot_key) holding `required: bool` and `hidden: bool`,
  defaulting to the code seed when absent.
- The CV Check-copy conditional lives in code; the settings screen shows it as "required when paid by
  check" and toggles whether that rule is active, not an unconditional flag.

## Data model

Add a nullable `kind` column (slot key, e.g. `signed_pr`, `vendor_quotation`, or NULL for Other) to
**both** attachment tables, avoiding any data/file migration:

- `document_attachments.kind` (String, nullable, indexed with `document_type`) — PR, PO, RR, CV.
- `accounts_payable_attachments.kind` (String, nullable) — AP.

A shared resolver, `app/attachments/completeness.py`, answers "which required slots for this document
are empty?" against whichever table the document uses, given the effective (per-company) required set.
It exposes:

- `missing_required(document_type, doc) -> list[slot]` — empty required slots now.
- `required_slots(document_type, doc) -> list[slot]` — effective required set, resolving the CV
  conditional from the document.
- A batched form, `incomplete_map(document_type, docs)` — one grouped query over the attachment table,
  for Action Items and badge counts (no per-document N+1).

Migrations are hand-written (batch `add_column` of a plain nullable String; no inline FK), verified
against a copy of a real database, per the project migration rules.

### Approval marker (durable, not audit-only)

`log_audit` commits on its own and swallows exceptions, so it cannot be the source of truth for the
badge. Add to each document a small durable marker written **in the same transaction as the approval**:

- `approved_incomplete_slots` (Text/JSON, nullable) — the list of required slots that were empty at
  the moment of approval, i.e. the **snapshot** of required-ness at approval time. NULL means "not
  approved incomplete" (or not yet approved).

The badge reads this snapshot intersected with *currently* still-missing slots, so completing the
document later clears the badge without rewriting the snapshot. An audit event is *also* written for
history, but the marker — not the audit row — drives the badge.

## UI: per-slot checklist panel

The shared panel (`app/attachments/templates/attachments/_panel.html`) becomes a checklist:

- One row per visible slot: label, status (`✓ attached` / `✗ missing`, required slots emphasised), the
  file(s) in that slot with download/preview/delete, and a per-slot upload control. Uploading through a
  slot's control sets that file's `kind` automatically.
- One "Other files" uploader beneath, for unlabeled attachments (`kind = NULL`).
- The checklist doubles as the at-a-glance completeness view an admin reads on the detail page.

Create-form queue (`_create_queue.html`) is unchanged in spirit; queued files land as Other and can be
moved into slots after the document exists, or the create form offers a per-slot queue (implementation
choice, panel parity preferred).

## Soft gate at approve / post

At each approval/posting route (PR/PO/RR `approve`, AP/CV `post`):

1. **Client:** if `missing_required` is non-empty, the Approve/Post button opens a confirm dialog
   listing exactly the missing slots ("Missing: Vendor Quotation"). Cancel stops; "Approve anyway"
   submits with an acknowledgement field.
2. **Server (authoritative):** the route recomputes `missing_required` itself. It never trusts the
   dialog. If non-empty, it proceeds (soft gate) but writes `approved_incomplete_slots` with the
   snapshot and an audit event "approved with missing: …", in the approval transaction. A direct POST
   that bypasses the dialog is handled identically — the exception is still recorded.
3. Deleting the file between dialog and submit is a non-issue: the server check runs at submit time.

The gate never blocks. It informs and records.

## Visibility

### Pre-approval — Action Items

A new category in `app/dashboard/action_items_service.py`: **"Documents missing required files"**,
listing draft/submitted documents (across the five types, branch-scoped, same audience rules as the
existing document categories) whose required slots are empty, naming what is missing. It uses the
batched `incomplete_map`. On approval the document leaves this list (it is no longer draft/submitted).
`count_action_items` includes it in the sidebar badge count with the same batched query.

### Post-approval — computed badge

Approved documents whose `approved_incomplete_slots` still intersects currently-missing slots show an
**"Incomplete" badge** on the detail page and list. The badge is computed, so adding the missing files
later clears it. This is the residual signal for records approved under the exception.

## Post-approval completion

- **PR, PO** already have an amendment path; filling an empty required slot uses it (approver-level).
- **RR, AP, CV** freeze attachments after approval today. This spec grants them **attachments-only**
  post-approval completion: an approver may add a file to a **still-empty required slot** (no editing
  or removing existing files, no financial or quantity change), recorded as an attachment revision in
  the audit trail. This is the minimum needed to clear an incomplete badge and honours BIR permanence —
  no posted journal entry or received quantity is touched.

## Deferred (separate spec, separate BIR review)

Full post-approval **amendment** of RR, AP and CV — adjusting received quantities (RR) or correcting
posted amounts/journal entries (AP, CV) — is explicitly out of scope. AP and CV are posted under BIR
permanence, where corrections are reversal JEs, not edits; that work needs its own design and review.
Tracked as a follow-up: `spec-post-approval-amendment-rr-ap-cv` (to be written).

## Edge cases

- **Config changed after approval:** the badge uses the approval-time snapshot, not current config, so
  un-requiring a slot does not retroactively clear or create incomplete flags on already-approved docs.
- **CV payment method:** check-copy requirement is fixed from the posted method; cash CVs never warn.
- **Historical documents:** grandfathered automatically — only the new approval code writes
  `approved_incomplete_slots`, so pre-existing approvals never carry it, and existing untagged files
  are never read as "missing".
- **Badge/Action-Items performance:** always computed via the batched grouped query, never per-document.
- **Audit write failure:** never blocks the business operation, and never the badge source (the durable
  marker is).
- **AP separate table:** the `kind` column and the shared resolver span both tables; no file migration.

## Security

No new exposure. Files remain access-controlled by the existing attachment routes; download/preview
gates are unchanged. The soft gate is a deliberate business rule, not an authorization control. No PII
handling, secrets, or public endpoints are introduced.

## Decisions Log

| ID | Topic | Decision | Rationale | Source | Date |
|---|---|---|---|---|---|
| D1 | Labeling model | Named slots per type + free "Other" | A required-check needs stable identity; free-typed labels defeat it on a typo | Interview | 2026-09-15 |
| D2 | Slot config location | Per-company, in Company Settings | philgen and ric may differ; owner-editable without deploy | Interview | 2026-09-15 |
| D3 | Required slots | PR: Signed PR. PO: Signed PO + Vendor Quotation. RR: Signed RR + Vendor DR/SR. AP: Signed AP. CV: Signed CV + Check copy (if by check) | Matches the owner's document list; check copy conditional on payment method | Interview | 2026-09-15 |
| D4 | AP table split | Add nullable `kind` to both `document_attachments` and `accounts_payable_attachments`; shared resolver | Avoids migrating 153 live AP files; one completeness check spans both | Interview | 2026-09-15 |
| D5 | Assignment UX | Per-slot checklist panel with per-slot upload + "Other" uploader | Tagging is automatic; checklist doubles as the at-a-glance completeness view | Interview | 2026-09-15 |
| D6 | Soft gate | Confirm dialog listing missing slots; proceed on explicit "Approve anyway" | A conscious, one-time decision before proceeding — the requested "hint before proceeding" | Interview | 2026-09-15 |
| D7 | Exception record | Durable approval-time marker + audit event; live computed badge | Admin sees it at a glance; badge self-heals; marker (not swallow-prone audit) is source of truth | Interview + Red Team | 2026-09-15 |
| D8 | Pre-approval visibility | New Action Items category; drops off on approval | Owner request: flag missing docs in Action Items; complete once approved | Interview | 2026-09-15 |
| D9 | Post-approval residue | Keep a computed "Incomplete" badge on approved-with-missing records | Owner request: also keep a residual signal after approval | Interview | 2026-09-15 |
| D10 | Late completion (this spec) | Attachments-only: fill empty required slots post-approval on RR/AP/CV; recorded as attachment revision | Clears the badge without touching financial content; honours BIR permanence | Interview + Red Team | 2026-09-15 |
| D11 | Full amendment RR/AP/CV | Deferred to a separate spec with its own BIR review | Editing posted JEs/quantities is a materially different, higher-risk change | Interview | 2026-09-15 |
| D12 | Config editability | Toggle required flag on seeded slots; no owner-created/renamed slots | Keeps labels consistent so the required-check is reliable; least UI | Interview | 2026-09-15 |
| D13 | Retroactive scope | Only documents approved after ship; historical grandfathered | Untagged existing files would falsely read as "missing"; avoids reopening closed BIR periods | Interview | 2026-09-15 |
| D14 | Server authority | Server recomputes missing-required at approve/post; dialog is advisory | A direct POST could bypass the client dialog; the exception must still record | Red Team | 2026-09-15 |
| D15 | Badge basis | Required-ness snapshotted at approval, intersected with current attachments | Later config changes must not rewrite history; completing the doc still clears the badge | Red Team | 2026-09-15 |
| D16 | CV check rule timing | Evaluated at post time from the posted payment method, snapshotted | Consistent with freezing required-ness at approval; posted CDVs are immutable | Red Team | 2026-09-15 |
| D17 | Performance | Batched grouped query for Action Items and badge counts | Badge count runs on every page; no per-document N+1 | Red Team | 2026-09-15 |

## Dependency Graph & Implementation Order

```
1. Data model              → migration: kind on both attachment tables;
                             approved_incomplete_slots marker on the 5 documents
2. Slot registry           → seeded slots + required defaults per type (extends registry.py)
   (depends on 1)            + CV conditional
3. Completeness resolver   → app/attachments/completeness.py: missing_required,
   (depends on 2)            required_slots, incomplete_map (batched)
4. Company Settings config → per-company required/hidden overrides feeding the resolver
   (depends on 3)
5. Checklist panel UI      → per-slot rows, per-slot upload sets kind, "Other" uploader
   (depends on 3, 4)
6. Soft gate               → server recheck + snapshot marker + audit at approve/post;
   (depends on 3)            confirm dialog on the 5 routes
7. Action Items category   → pre-approval "missing required files" list + count
   (depends on 3)
8. Post-approval badge     → computed from marker ∩ current attachments, detail + list
   (depends on 3, 6)
9. Late completion         → attachments-only fill of empty required slots on RR/AP/CV
   (depends on 5, 8)
```

Build order: 1 → 2 → 3, then 4/5/6/7/8 (each depends on 3; 8 also on 6), then 9. Each step is
independently testable; ship 1–8 as the feature, 9 to close the RR/AP/CV completion gap.

## Implementation checklist

- [ ] **1. Data model.** Migration (hand-written, batch `add_column`, verified on a DB copy): add
      nullable indexed `kind` to `document_attachments` and nullable `kind` to
      `accounts_payable_attachments`; add nullable `approved_incomplete_slots` (JSON/Text) to
      PurchaseRequest, PurchaseOrder, ReceivingReport, AccountsPayable, CashDisbursementVoucher.
- [ ] **2. Slot registry.** Extend `app/attachments/registry.py` with seeded slots + default required
      flags per document type, and the CV "check copy when paid by check" conditional.
- [ ] **3. Completeness resolver.** `app/attachments/completeness.py`: `required_slots`,
      `missing_required`, batched `incomplete_map`. Unit tests over the slot/required matrix.
- [ ] **4. Company Settings config.** Per-company required/hidden overrides per (document_type, slot),
      defaulting to the code seed; wire into the resolver. Owner cannot add/rename slots.
- [ ] **5. Checklist panel.** Rewrite `attachments/_panel.html` to per-slot rows (status, per-slot
      upload sets `kind`) + "Other files" uploader. Route to set/read `kind`.
- [ ] **6. Soft gate.** On PR/PO/RR `approve` and AP/CV `post`: server recomputes `missing_required`,
      writes `approved_incomplete_slots` snapshot + audit event in the approval transaction; confirm
      dialog on the client listing missing slots. Integration tests incl. direct-POST bypass.
- [ ] **7. Action Items category.** "Documents missing required files" (draft/submitted, branch-scoped,
      batched); include in `count_action_items`. Drops off on approval.
- [ ] **8. Post-approval badge.** Computed from `approved_incomplete_slots` ∩ currently-missing, on
      detail and list pages; self-heals when completed.
- [ ] **9. Late completion.** Attachments-only fill of empty required slots on approved RR/AP/CV
      (approver-level, recorded as an attachment revision); no financial/quantity change.
