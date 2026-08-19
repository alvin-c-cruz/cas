"""Shared document-number generator, scope-configurable per client.

Every CAS document generator (PR, PO, DR, RR, Quotation, and the two memo
types) delegates here, so the numbering POLICY lives in one place instead of
being copy-pasted seven times.

Scope comes from the `document_number_scope` key in `app_settings`:

  'company'  one series shared across every branch. THE DEFAULT, and what every
             existing client already does -- the absence of the key is the safe
             state, so a client sees no behaviour change until someone sets it.
  'branch'   each branch climbs its own series.

Any other value falls back to 'company': a typo in a settings row must not
silently re-number a client's documents.

WHY THE BRANCH PATH IS NOT JUST A FILTER
Document number columns are SINGLE-COLUMN GLOBAL unique indexes (`unique=True`)
-- there is no (branch_id, number) composite anywhere in CAS. So two branches
must never produce the same string, which splits the branch path in two:

  * The branch HAS prior numbered documents -> continue its series, skipping
    past any number already taken globally. Continuing a series is a mechanical
    fact; there is nothing to guess. This is what makes a mid-year flip from
    'company' to 'branch' survivable: under company scope the two branches drew
    from one interleaved pool, so their maxima are necessarily ADJACENT and the
    naive next value belongs to the other branch.
  * The branch has NONE -> return '00001' verbatim, WITHOUT skipping. STARTING a
    series is a business decision the system must never guess. The caller types
    the real start (e.g. '50001'); if they forget, the callers' existing
    duplicate check refuses the save. It fails loudly instead of silently
    merging two branches' ranges.

Callers must NOT rely on this function raising -- the GET prefill call sites sit
outside any try/except, where a raise is a 500 rather than a flash.
"""
from app import db
from app.settings import AppSettings

SCOPE_KEY = 'document_number_scope'
COMPANY = 'company'
BRANCH = 'branch'

PAD = 5


def _resolve_scope():
    """The stored scope, defaulting to (and falling back to) company-wide."""
    value = AppSettings.get_setting(SCOPE_KEY, COMPANY)
    return BRANCH if value == BRANCH else COMPANY


def next_document_number(model, column, branch_id=None, filters=None):
    """Return the next document number for `model`.`column`, zero-padded to 5.

    `filters` is applied under BOTH scopes -- it narrows what counts as "the
    same series" regardless of branch (the memo generators pass their
    `memo_type` this way, because a Credit Memo and a Debit Note are different
    documents sharing one table, not one series split by scope).

    Only purely-numeric existing values participate. Legacy prefixed numbers
    ('PR-2026-07-0030') are invisible here, exactly as the seven generators this
    replaces always treated them, so a client transitioning off that format
    starts cleanly and never collides with old rows.
    """
    query = db.session.query(column, model.branch_id)
    for criterion in (filters or []):
        query = query.filter(criterion)

    all_nums = set()
    branch_nums = set()
    for value, row_branch_id in query.all():
        if not value or not value.isdigit():
            continue
        number = int(value)
        all_nums.add(number)
        if branch_id is not None and row_branch_id == branch_id:
            branch_nums.add(number)

    # branch_id=None under branch scope means the caller has no branch in hand;
    # fall back to the shared series rather than inventing a NULL-branch one.
    if _resolve_scope() == BRANCH and branch_id is not None:
        if not branch_nums:
            # Starting a series -- never guessed, never skipped forward.
            return f'{1:0{PAD}d}'
        candidate = max(branch_nums) + 1
        while candidate in all_nums:
            candidate += 1
        return f'{candidate:0{PAD}d}'

    next_num = (max(all_nums) + 1) if all_nums else 1
    return f'{next_num:0{PAD}d}'


def assigned_number_or_raise(model, column, number, label):
    """Return `number`, or raise ValueError if it is already taken.

    ONLY for the ASSIGNED call sites -- Quotation, Sales Memo, Vendor Memo --
    which have no number field on the form, so a collision there would surface
    as an IntegrityError and a generic "An error occurred" the user cannot
    escape. All three views already catch ValueError and flash it verbatim, so
    this needs no new error plumbing.

    Deliberately NOT called by next_document_number itself: the GET prefill call
    sites sit outside any try/except, where a raise is a 500 rather than a
    flash. Those sites are already protected by their own duplicate check on
    POST, which the user can act on because they have a field to retype.

    The collision this catches is a brand-new branch under 'branch' scope: it
    has no series, so the engine returns the '00001' placeholder, and there is
    no field for the user to type the real start into.
    """
    exists = db.session.query(column).filter(column == number).first()
    if exists:
        raise ValueError(
            f'{label} number {number} is already in use. This branch has no '
            f'starting number for {label.lower()}s -- ask an administrator to '
            f'record the first one.')
    return number
