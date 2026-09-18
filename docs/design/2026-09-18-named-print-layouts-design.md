# Named print layouts, selected per workstation

**Date:** 2026-09-18
**Status:** Approved design, pending implementation plan
**Scope:** Replace the single shared pre-printed layout per branch with a named
library of layouts, and let each **workstation** choose which one it prints
with. Purchase Orders only in this build; the mechanism is built generically so
the other eleven document types can adopt it later without redesign.

---

## Problem

Philgen prints purchase orders onto pre-printed stock, so the layout is absolute
coordinates tuned to one physical printer. An alignment that is correct on the
Malandag LX-310 overprints on an HP LaserJet.

The app stores **one** PO layout per branch —
`app_settings['po_preprinted_layout:<branch_id>']`, 2117 bytes for branch 1 —
shared by every user. Whoever saves the designer last overwrites everyone else.
`User.can_edit_print_layout` already names this as the reason its access was kept
to a whitelist:

> the stored layout is BRANCH-WIDE — one person's drag changes every future
> printout for that branch

There are two purchasers, a third joining shortly, and they move between
workstations and printers. Each move is a silent misalignment that costs a pad of
pre-printed forms before anyone notices.

## Goals

- Many named layouts per document type and scope, not one.
- "Save as…" in the designer with a user-supplied name.
- A dropdown to choose the active layout, on both the print screen and the
  designer — meaning different things in each (see *Key semantics*).
- The choice persists server-side, survives logout, and is not `localStorage`.
- A shared library: any user may select any layout.
- Names are editable, and shown wherever a layout is selected.
- **Printing a PO immediately before and after the migration produces identical
  sheets.** This is the criterion that matters; a broken alignment costs stock.

## Non-goals

- Any document type other than Purchase Orders in this build.
- Removing the legacy `app_settings` keys. They stay for one release.
- Decomposing the layout JSON into columns.
- Per-printer *driver* settings (margins, paper source). This is overlay
  geometry only, exactly what is stored today.

## Key semantics (decisions)

These were settled in discussion on 2026-09-18 and should not be re-derived.

1. **Selection is per workstation, not per user.** The original request said the
   choice should follow the user to another machine, and also that "a layout
   belongs to a PRINTER, not a person". Those contradict: a purchaser who walks
   to a different desk and carries their layout with them prints on the wrong
   printer's alignment — the exact failure this feature exists to remove, now
   wearing a name that makes it look deliberate. Resolved to per-device.

2. **The device pref is shared by everyone at that workstation** — there is no
   `user_id` on it at all. If a layout belongs to a printer and a workstation
   prints to one printer, the machine's choice is the right answer for whoever
   sits down. A new purchaser sits at the Malandag desk and prints correctly with
   no setup, which is the stated blocker for hiring.

3. **The designer's dropdown loads a layout for editing; it does not change what
   the workstation prints with.** Repointing the workstation is a separate,
   explicit action. Otherwise an accountant sitting at the Malandag desk who
   opens the designer to fix the LaserJet's alignment silently repoints Malandag
   at the LaserJet layout, and the next purchaser prints misaligned.

4. **Permissions widen nothing and narrow one thing.** Create/edit/save/rename
   keep the existing `can_edit_print_layout` (admin, chief_accountant,
   accountant, staff). Delete narrows to admin/chief_accountant, being the only
   action with cross-machine blast radius. Note the original proposal
   (create/edit/delete = accountant/admin) would have *removed* an ability staff
   have today and blocked the purchaser this feature is for, who is staff.

5. **The migration copies payloads byte for byte, never re-sanitized.** A stored
   layout is sanitized at *read* time against whatever the defaults currently
   are. Sanitizing at *write* time instead would bake today's defaults into a
   value that was hand-aligned on paper months ago. Raw copy plus the existing
   read-time sanitize is what makes "identical sheets" provable.

## Existing structure this builds on

`app/common/preprinted_base.py:436` exposes
`build_layout_api(setting_key, field_keys, default_layout, audit_module, audit_identifier)`,
returning `(sanitize_layout, get_layout, save_layout)`. **Only three of twelve
modules use it** — `purchase_orders`, `purchase_requests`, `receiving_reports`.
The other eight are hand-rolled copies of 241–372 lines, and
`cash_disbursements/check_layout.py` is different again (scoped by cash account,
not branch).

All twelve nonetheless expose the same signatures — `get_layout(branch_id=None)`
and `save_layout(raw, username, branch_id=None)` — which is what lets new storage
slide in behind them one module at a time.

PO resolves its layout at exactly one call site:
`app/purchase_orders/views.py:1172`, `layout=get_layout(po.branch_id)`.

## 1. Data model

```
print_layouts
  id            INTEGER PK
  doc_type      VARCHAR(40)  NOT NULL   'purchase_orders' (the audit module name)
  scope_id      INTEGER      NOT NULL   branch_id today; cash_account_id when
                                        cd_check adopts this; 0 = unscoped
  name          VARCHAR(100) NOT NULL   "Purchasing - LX-310 Malandag"
  payload       TEXT         NOT NULL   the sanitized layout JSON, as stored today
  is_default    BOOLEAN      NOT NULL DEFAULT 0
  created_by_id INTEGER      FK users.id
  created_at    DATETIME     NOT NULL   ph_now
  updated_by_id INTEGER      FK users.id
  updated_at    DATETIME     NOT NULL   ph_now
  UNIQUE (doc_type, scope_id, name)
  UNIQUE INDEX (doc_type, scope_id) WHERE is_default = 1

print_layout_device_prefs
  id            INTEGER PK
  device_id     VARCHAR(64)  NOT NULL   opaque uuid4 from the cas_device_id cookie
  doc_type      VARCHAR(40)  NOT NULL
  scope_id      INTEGER      NOT NULL   0 = unscoped, as above
  layout_id     INTEGER      FK print_layouts.id  ON DELETE SET NULL
  label         VARCHAR(100) NULL       optional human name for the workstation
  updated_at    DATETIME     NOT NULL
  UNIQUE (device_id, doc_type, scope_id)
```

**`payload` stays TEXT holding the same JSON**, not decomposed into columns. The
entire safety argument in `preprinted_base.py` rests on `sanitize_layout()` being
the only way a layout is read or written; columns would fork that. Byte-identical
payload is also what makes AC 6 checkable by diff.

**`ON DELETE SET NULL`, not CASCADE.** A deleted layout must leave the workstation
pointing at nothing and falling through to the default, not delete the
workstation's row.

**`scope_id` is NOT NULL with `0` meaning unscoped**, rather than nullable. SQLite
treats NULLs as distinct in a UNIQUE constraint, so a nullable `scope_id` would
let two rows share `(doc_type, NULL, 'Default')` and quietly defeat the
uniqueness the design depends on. The legacy unscoped key migrates to
`scope_id = 0`. The same reasoning applies to the device-pref unique key.

**At most one default per scope is enforced by a partial unique index**, not by
application code. Resolution step 2 asks for "the `is_default` row"; two of them
makes that question unanswerable and the answer would vary by row order. SQLite
supports `CREATE UNIQUE INDEX ... WHERE is_default = 1`; setting a new default
must clear the old one in the same transaction.

**`scope_id` is deliberately not a branch FK**, because `cd_check` scopes by cash
account. A real FK now would have to be dropped later, and `CLAUDE.md` warns that
SQLite batch mode cannot reproduce a constraint it cannot name.

Both tables are **company/instance-wide, not branch-scoped rows** in the usual
sense — `scope_id` *is* the branch. This is a documented exception to "every new
transactional model carries `branch_id`": these are configuration, like
`app_settings`, not transactions.

### Consequence to accept

`UNIQUE (doc_type, scope_id, name)` over a shared library means two purchasers
cannot both create "My Layout". Names are branch-wide and visible to everyone.
That is intended given layouts describe printers, but the UI copy must push
people toward printer names — see §3.

## 2. Resolution and migration

### Resolution

`get_layout(branch_id=None, device_id=None)` — the new argument is optional, so
every existing caller keeps working and simply gets the default.

1. this device's pref → that layout row
2. else the `is_default` row for (doc_type, scope_id)
3. else the first row for that scope, by id
4. else legacy `app_settings['po_preprinted_layout:<branch_id>']`
5. else legacy unscoped `app_settings['po_preprinted_layout']`
6. else the hardcoded `default_layout`

Never a hard failure, at any step. Steps 4–5 are the read-through that keeps the
migration reversible. The result is passed through the existing
`sanitize_layout()` exactly as today, including the fail-safe `except` that
degrades a corrupt payload to defaults — the print page hosts the designer, so a
raise there would leave a branch with no UI to fix itself with.

### Migration

1. For each existing `po_preprinted_layout*` key, insert one `print_layouts` row:
   - `name` = "Default - CORP" / "Default - EXTRA" from the branch name; the
     unscoped key becomes "Default".
   - `payload` = the stored string **copied raw**.
   - `is_default` = true, `scope_id` = the branch id (NULL for the unscoped key).
2. **Keep the old keys.** Do not delete them in this release.
3. Create **no** device prefs. Every workstation therefore falls through to
   `is_default` and day one is unchanged.

Hand-written, with batch operations and explicitly named FK constraints, per
`CLAUDE.md`. Verified against a **copy of the real philgen database**, not a
`create_all()` test DB — `tools/verify_r08_migration.py` is the worked example.

### Dual-write during the transition

Saving the `is_default` layout **also** writes the legacy
`po_preprinted_layout:<branch_id>` key. A rollback then keeps every alignment
tweak made since the migration, not merely the state at migration time. Named
non-default layouts have nowhere to go in the old schema and are lost on
rollback; they are new work that old code could not use anyway.

The dual-write is transitional and must be removed in the same release that drops
the legacy keys. It is the one place the two stores can disagree, so it gets its
own test.

## 3. Interface

### Designer

```
Editing: [ Purchasing - HP LaserJet ▾ ]  [Save] [Save as…] [Rename] [Delete]
This workstation uses: Purchasing - LX-310 Malandag   [ Use on this workstation ]
```

The second line is what makes the accountant-at-the-wrong-desk case visible
rather than silent. "Use on this workstation" is the only control in the designer
that writes a device pref.

### Print screen

```
Printing with: [ Purchasing - LX-310 Malandag ▾ ]
```

Changing it writes the device pref immediately and re-renders.

### Copy

Layout names describe **printers, not people**. The "Save as…" dialog says so in
its helper text, and suggests the shape "Area - Printer" ("Purchasing - LX-310
Malandag"). Without this, each purchaser duplicates the same printer's layout
under their own name and the library rots.

### Permissions

| Action | Who |
|---|---|
| Select, "Use on this workstation" | anyone who can reach the print screen |
| Create, edit, Save, Save as…, Rename | `can_edit_print_layout` — admin, CA, accountant, staff (unchanged) |
| Delete | new `can_delete_print_layout` — admin, CA |

`can_delete_print_layout` is a new property on `User` beside
`can_edit_print_layout`, carrying its own docstring explaining why deletion is
narrower — one named rule rather than a repeated role tuple, following the
precedent set when `can_edit_print_layout` replaced eleven copies.

### Device identity

A `cas_device_id` cookie: uuid4, long-lived, `HttpOnly`, `SameSite=Lax`, `Secure`
in production, set lazily on first visit to a print screen.

Deliberately **not** company-scoped, unlike `cas_philgen` / `cas_ric`: philgen and
ric on one machine are the same physical printer, and the pref rows live in each
company's own database, so nothing leaks. A cleared cookie means a new device with
no pref, falling through to `is_default` — degraded, never wrong.

## 4. Edge cases

- **No layouts at all** (fresh install, nothing to migrate): the dropdown shows
  "Default" backed by the hardcoded defaults; the first save creates the row.
- **Deleted layout still selected elsewhere**: `SET NULL` leaves the pref row;
  resolution falls to `is_default`; the print screen warns that the chosen layout
  no longer exists.
- **Promoting a new default**: clearing the old `is_default` and setting the new
  one happens in one transaction, or the partial unique index rejects it.
- **`is_default` deleted**: refuse. There must always be a default to fall back
  to, or resolution step 2 has nothing to answer with.
- **Renaming**: touches `name` only. Prefs hold `layout_id`, so no selection can
  move.
- **Two tabs, same workstation, different layouts**: last write wins on the
  device pref. Acceptable — it is one machine with one printer.
- **Corrupt payload**: unchanged behaviour, degrades to defaults via the existing
  fail-safe.

## 5. Testing

| Acceptance criterion | Test |
|---|---|
| 1 Two named layouts, neither overwrites | two saves under different names; both rows exist, both listed |
| 2 Selection follows the **workstation** | pref survives logout and a different user at the same device (reinterpreted per decision 1) |
| 3 Switching persists to next login | pref read after session teardown |
| 4 Deleting a selected layout | `SET NULL` → falls back to `is_default`, warns, printing still works |
| 5 Renaming does not change selection | rename, assert `layout_id` and resolution unchanged |
| 6 **Identical sheets before/after migration** | `get_layout()` returns an identical dict, **and** the rendered print HTML is byte-identical |

Beyond the stated criteria:

- The designer's dropdown does **not** repoint the workstation (decision 3).
- Delete is refused for `staff`, allowed for admin/CA.
- Dual-write keeps the legacy key in step when `is_default` is saved, and does
  not write for a non-default layout.
- A cleared/absent cookie resolves to `is_default` rather than failing.
- Two rows cannot share a name within a scope, and two rows cannot both be
  `is_default` for one scope — asserted against the real constraints, since both
  are the kind of rule that silently does nothing if the index is mis-declared.
- Audit rows are written for create, save, rename and delete, verified through
  the real HTTP route rather than the service layer — and via
  `get_changes(old, new, fields)`, never `old_values={}`.

AC 6 is the one that must not be taken on trust: it is verified against a copy of
the real philgen database, with the actual `po_preprinted_layout:1` payload, not a
synthetic layout.

## Files touched

- `app/print_layouts/models.py` — new; both tables.
- `migrations/versions/<rev>_print_layouts.py` — new; hand-written.
- `app/common/preprinted_base.py` — `get_layout`/`save_layout` gain the resolution
  chain and dual-write; signature extended, not changed.
- `app/purchase_orders/views.py` — pass `device_id` at the print call site; new
  routes for save-as/rename/delete/select.
- `app/static/js/po_preprinted_designer.js` — the dropdown and the four buttons.
- `app/purchase_orders/templates/purchase_orders/print_preprinted.html` — toolbar.
- `app/users/models.py` — `can_delete_print_layout`.
- Tests per §5.

## Rollout

1. Deploy behind the read-through: with no `print_layouts` rows, resolution falls
   to step 4 and behaviour is exactly as today.
2. Run the migration. Every workstation still resolves to `is_default`.
3. **Print one PO and compare it against a sheet printed before the migration.**
   Paper, not a screenshot.
4. Create the second named layout and point the second workstation at it.
5. One release later: remove the dual-write and drop the legacy keys, in a change
   of its own.

Rollback at any point before step 5 is `git revert` plus the pre-deploy database
copy; the legacy keys are still authoritative for old code.
