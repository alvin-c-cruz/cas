# Document Numbering Scope — how it works, and how to flip it

CAS numbers documents from one shared engine, `app/utils/doc_numbering.py`. Seven generators
delegate to it: Purchase Request, Purchase Order, Delivery Receipt, Receiving Report, Quotation,
Vendor Memo and Sales Memo.

## The two scopes

The scope lives in one `app_settings` row, `document_number_scope`:

| Value | Behaviour |
|---|---|
| `company` | One series shared across every branch: `00001`, `00002`, `00003`… **The default.** An absent key, or any unrecognised value, resolves to this. |
| `branch` | Each branch climbs its own series independently. |

**The absence of the key is the safe state.** No client changes behaviour until someone sets it
deliberately, which is why there is no Company Settings field for it — see below.

Under `company` scope the series interleaves across branches in creation order. A requisition
raised in CORP takes `00001`; the next one, raised in EXTRA, takes `00002`. That is one continuous
company-wide run, and it is what most clients want.

## Why there is no settings-screen toggle

Flipping this mid-year is the riskiest action in the numbering system (see below), and it is a
once-per-client onboarding decision, not an operational control. Putting it behind a dropdown that
every admin can nudge maximises the chance of the one failure mode worth avoiding. Set it from the
command line instead:

```
flask set-document-number-scope branch     # or: company
```

The command refuses any other value, prints `old -> new`, and warns when the database already holds
numbered documents.

## Flipping company → branch on a live database

Document number columns are **single-column global unique indexes** — there is no
`(branch_id, number)` composite anywhere in CAS — so two branches must never produce the same
string.

This matters at the flip because under `company` scope both branches drew from **one interleaved
pool**, which means their highest numbers are necessarily **adjacent**. Branch A holds `00598`,
branch B holds `00600`; A's naive next value is `00599`, which B already used.

The engine handles this automatically: when a branch already has a series, its next number is
**skipped forward past anything taken globally**, so A gets `00601` rather than colliding. Nothing
breaks. But the two series remain **interleaved** until you separate them.

**Runbook:**

1. Run `flask set-document-number-scope branch`. Read the warning it prints.
2. Expect the first few documents per branch to carry numbers close to each other. This is
   cosmetic, not a fault.
3. Separate the ranges deliberately: on each secondary branch's next document that has a **typed**
   number field (Purchase Request, Purchase Order, Receiving Report, Delivery Receipt), type a
   high start — e.g. `50001`. Every subsequent number in that branch climbs from there on its own.
4. From then on, each branch maintains its own run with no further intervention.

**The reverse flip (`branch` → `company`) is inherently safe** — a global `max + 1` is greater than
every branch maximum, so it cannot collide.

## Starting a series is never guessed

When a branch has **no** prior numbered document, the engine returns `00001` verbatim and does
**not** skip forward, even if `00001` is already taken elsewhere. Choosing where a branch's series
starts is a business decision the system must never make on its own. The user types the real start
and, if they forget, the save is refused loudly rather than silently merging two branches' ranges.

**Known limitation.** Quotation, Sales Memo and Vendor Memo have **no number field on the form** —
their numbers are assigned server-side. So in a brand-new branch under `branch` scope, the first
document of those three types cannot be started by typing over the placeholder. It fails with an
actionable message instead of a generic error, but the branch still needs its series seeded another
way. The fix — giving those three an optional blank-by-default number field, mirroring the Delivery
Receipt pattern — is a separate piece of work.

## Two rules worth knowing

**`memo_type` is not a scope axis.** A Credit Memo and a Debit Note are different documents sharing
one table, so they keep separate series under **both** scopes. The delegate passes `memo_type` as an
unconditional filter; under `branch` scope the series key becomes `(memo_type, branch)`.

**Person beats branch on the Purchase Order pad.** `next_po_number_for(user_id)` suggests the next
number off a purchaser's own physical pre-printed pad, and stays scoped to that purchaser regardless
of scope — filtering her POs by branch as well would split one paper pad into two series. Branch
scope enters only at the fallback, when the purchaser has no prior PO and there is no pad to read.
