"""Every P2P status tuple must classify every status its document can reach.

THE GENERALISATION of TestEveryLifecycleStatusIsClassified, which was written
for COMMITTED_PO alone after BUG-SUBMITTED-PO-NOT-COUNTED-IN-PR-ALLOCATION
(2026-08-26). Backlog 304.

The bug was not "a tuple was wrong". It was that a status was added to the
purchase order's lifecycle and a tuple in ANOTHER module silently enumerating
that lifecycle was never revisited. Nothing failed. The new state was simply
invisible to everything that read the tuple.

That shape is not unique to COMMITTED_PO -- the purchase area holds TEN such
tuples across three documents, and every one of them is a hand-kept enumeration
of a lifecycle nothing forces it to track. So the guard is parameterised over a
registry rather than written once for the tuple that already bit us:

  1. the DOCUMENT lifecycles are source-scraped, never hand-listed (a hand-kept
     list is the same second enumeration that caused the bug, and would drift
     the same way);
  2. every registered tuple must place every scraped status either INSIDE
     itself or in its own EXCLUDED_ON_PURPOSE, with a reason;
  3. the REGISTRY ITSELF is checked for completeness by scraping the P2P
     modules for status collections -- otherwise the registry is just one more
     hand-kept list, and the eleventh tuple would be invisible exactly the way
     `submitted` was.

Every layer has a guard on the guard: a scraper that silently returns nothing
would make the test above it pass vacuously, which is the failure mode this
whole file exists to prevent.

KNOWN LIMIT: step 3 finds NAMED collections only. An inline literal such as
`if po.status not in ('draft', 'submitted')` cannot be registered and is not
seen. There are four of those in the purchase area today; naming them is a
separate change.
"""
import pathlib
import re

import pytest

from app.purchase_orders.models import PurchaseOrder
from app.purchase_orders.utils import OPEN_PO_STATUSES
from app.purchase_requests.allocation import (
    APPROVED_PR, COMMITTED_PO, PULLABLE_PR, RECOMPUTABLE_PR)
from app.purchase_requests.models import PurchaseRequest
from app.receiving_reports.models import COMMITTED_STATUSES as RR_COMMITTED
from app.receiving_reports.views import RECEIVABLE_PO_STATUSES
from app.purchase_billing import _RECEIVABLE_PO

pytestmark = [pytest.mark.unit, pytest.mark.purchase_requests]

APP = pathlib.Path(__file__).resolve().parents[2] / 'app'

#: The modules whose status tuples this file is responsible for. Bounded on
#: purpose: the sell-side mirrors (delivery_receipts, sales_orders) have the
#: identical shape and deserve the identical guard, but claiming to cover them
#: from a file named for the purchase area would be a coverage claim nobody
#: could check. Widen this list, not the docstring.
P2P = ('purchase_requests', 'purchase_orders', 'receiving_reports',
       'purchase_billing.py')


# -- layer 1: what statuses can each document actually reach? ------------------

#: variable name each document is bound to at its `.status = '...'` write sites,
#: and the statuses that must turn up if the scrape is working at all.
DOCUMENTS = {
    'purchase order': ('po', {'draft', 'submitted', 'approved', 'cancelled',
                              'closed'}),
    'purchase requisition': ('pr', {'draft', 'submitted', 'approved',
                                    'rejected', 'cancelled', 'converted',
                                    'partially_converted'}),
    'receiving report': ('rr', {'draft', 'submitted', 'approved', 'cancelled',
                                'billed'}),
}

#: Statuses that appear in a registered tuple but that NOTHING in the app ever
#: assigns. Declared so a TYPO in a tuple -- a filter that silently matches no
#: row -- is a test failure rather than a permanent no-op.
INERT = {
    'partially_received':
        'declared in every purchase-order tuple and never assigned by any code '
        'path; the PO -> partially_received transition has not shipped. Kept '
        'because removing it would change behaviour only if something started '
        'to write it.',
}


def statuses_written_by_the_app(var):
    """Every literal assigned to *var*.status anywhere under app/.

    Tree-wide rather than over a hand-kept file list. The original guard named
    two files, which was correct on the day it was written and is precisely the
    kind of second enumeration this test exists to distrust: a new module
    writing po.status would not have been seen.
    """
    pattern = re.compile(r'\b%s\.status\s*=\s*[\'"]([a-z_]+)[\'"]' % var)
    found = set()
    for path in APP.rglob('*.py'):
        found |= set(pattern.findall(path.read_text(encoding='utf-8')))
    # The column default. A document's FIRST status is never assigned, so no
    # scrape can see it.
    found.add('draft')
    return found


@pytest.mark.parametrize('doc', sorted(DOCUMENTS))
def test_the_lifecycle_scrape_finds_the_known_statuses(doc):
    """GUARD ON THE GUARD. If the scrape returns nothing -- a refactor renamed
    the variable, the writes moved behind a helper -- every classification test
    below would pass vacuously against an empty set."""
    var, expected = DOCUMENTS[doc]
    found = statuses_written_by_the_app(var)
    missing = expected - found
    assert not missing, (
        'The %s lifecycle scrape no longer finds %s. Either those transitions '
        'were removed, or the scrape broke and every tuple below is now being '
        'checked against an incomplete lifecycle -- which is the vacuous pass '
        'this file is built to refuse.' % (doc, sorted(missing)))


# -- layer 2: the registry ----------------------------------------------------

class Tuple_:
    """One status collection, and the decision behind every status it omits."""

    def __init__(self, name, members, doc, question, excluded, known_gap=None):
        self.name = name
        self.members = tuple(members)
        self.doc = doc
        self.question = question          # what the tuple decides, in one line
        self.excluded = excluded          # status -> why it is left out
        self.known_gap = known_gap or {}  # status -> tracker reference

    def __repr__(self):
        return self.name


REGISTRY = [
    # -- purchase order lifecycle ---------------------------------------------
    Tuple_(
        'purchase_requests.allocation.COMMITTED_PO', COMMITTED_PO,
        'purchase order',
        'do this order\'s lines consume their requisition line\'s quantity?',
        {
            'cancelled':
                'a cancelled order releases its lines -- the reason allocation '
                'is derived and never stored',
        }),
    Tuple_(
        'purchase_orders.utils.OPEN_PO_STATUSES', OPEN_PO_STATUSES,
        'purchase order',
        'does this order count towards the list page\'s "Open" card and open '
        'value total?',
        {
            'draft':
                'counted by its own card -- compute_po_summary counts '
                "status == 'draft' exactly for draft_count",
            'cancelled':
                'a withdrawn order is not open work, and deliberately appears '
                'in no card',
            'closed':
                'counted by its own card (closed_count); "Open" is labelled '
                '"approved, not yet closed"',
        },
        known_gap={
            'submitted':
                'FOUND 2026-08-27 generalising this guard. A submitted order '
                'is counted by NO card: draft_count matches draft exactly, '
                'open_count reads this tuple, closed_count matches closed. The '
                'card labelled "Draft / to approve" is exactly where an order '
                'awaiting approval belongs, so either this tuple or '
                'draft_count is wrong -- an owner decision, not a test fix. '
                'Same root cause as the bug this file was built for: the PO '
                'submit step (cas 579e12ed) shipped and its sibling '
                'enumerations were never revisited.',
        }),
    Tuple_(
        'purchase_orders.models.PurchaseOrder.AMEND_STATUSES',
        PurchaseOrder.AMEND_STATUSES, 'purchase order',
        'may a post-approval amendment be raised against this order?',
        {
            'draft':
                'edit() serves a draft directly; amendment is the '
                'POST-approval correction path and a draft has no need of it',
            'submitted':
                'pre-approval. A submitted order is resolved by approving or '
                'cancelling it, not by amending it -- amendment exists for an '
                'order already released',
            'cancelled':
                'a withdrawn order has nothing to amend',
            'closed':
                'billing sets it (purchase_billing.py), so a billed order is '
                'unreachable here by design',
        }),
    Tuple_(
        'receiving_reports.views.RECEIVABLE_PO_STATUSES',
        RECEIVABLE_PO_STATUSES, 'purchase order',
        'may a receiving report draw lines from this order?',
        {
            'draft':
                'not yet released -- goods received against it would have no '
                'commitment behind them',
            'submitted':
                'not yet authorised. The submit step hands the order to an '
                'approver; receiving is downstream of that decision',
            'cancelled':
                'the order was withdrawn, so there is nothing left to receive',
            'closed':
                'fully billed -- receiving more would exceed what was paid for',
        }),
    Tuple_(
        'purchase_billing._RECEIVABLE_PO', _RECEIVABLE_PO, 'purchase order',
        'may a bill draw on this order directly (the services / no-receipt '
        'path)?',
        {
            'draft': 'not yet released, so there is nothing to bill against',
            'submitted': 'not yet authorised -- billing is downstream of '
                         'approval',
            'cancelled': 'the order was withdrawn',
            'closed': 'already billed -- purchase_billing itself writes this '
                      'status, so accepting it would allow a second bill',
        }),

    # -- purchase requisition lifecycle ---------------------------------------
    Tuple_(
        'purchase_requests.allocation.PULLABLE_PR', PULLABLE_PR,
        'purchase requisition',
        'may this requisition\'s lines be pulled onto a purchase order?',
        {
            'draft':
                'nobody has been handed it yet -- submit is what offers a '
                'requisition to the rest of the process',
            'rejected':
                'one of the two exits FROM submitted, and so one of the two '
                'statuses the 2026-08-26 widening was most likely to leak into',
            'cancelled':
                'the other exit from submitted -- the demand was withdrawn',
            'converted':
                'every line is already fully ordered, so there is nothing left '
                'to pull',
        }),
    Tuple_(
        'purchase_requests.allocation.RECOMPUTABLE_PR', RECOMPUTABLE_PR,
        'purchase requisition',
        'may recompute_pr_status move this requisition?',
        {
            'draft':
                'nothing can order against it, so there is no allocation to '
                'recompute',
            'submitted':
                'THE LOAD-BEARING EXCLUSION, not an oversight. PULLABLE_PR '
                'admits submitted since 2026-08-26 and this tuple deliberately '
                'does not follow: approve() and reject() both require '
                "status == 'submitted' exactly, so recomputing a pulled "
                'requisition would move it to partially_converted or converted '
                'and the approval step would vanish silently, leaving an '
                'unauthorised requisition looking like a completed one',
            'rejected':
                'refused. Recomputing it back into the live set would be a '
                'real defect',
            'cancelled':
                'withdrawn. Resurrecting a cancelled requisition would be a '
                'real defect',
        }),
    Tuple_(
        'purchase_requests.allocation.APPROVED_PR', APPROVED_PR,
        'purchase requisition',
        'does this requisition count as APPROVED when releasing a purchase '
        'order?',
        {
            'draft': 'never authorised -- the whole point of the guard',
            'submitted':
                'awaiting authorisation. This is THE status the guard exists '
                'for: a submitted requisition may be pulled early, but the '
                'order it feeds may not be approved until it is',
            'rejected': 'authorisation was refused',
            'cancelled': 'the demand was withdrawn',
        }),
    Tuple_(
        'purchase_requests.models.PurchaseRequest.AMEND_STATUSES',
        PurchaseRequest.AMEND_STATUSES, 'purchase requisition',
        'may a post-approval amendment be raised against this requisition?',
        {
            'draft': 'edited directly; amendment is the post-approval path',
            'submitted':
                'pre-approval. A submitted requisition is resolved by '
                'approving or rejecting it',
            'rejected': 'no live demand to amend',
            'cancelled': 'no live demand to amend',
            'converted':
                'every line is consumed, so the only edit the validator would '
                'permit is ADDING demand to a fully ordered requisition -- '
                'which belongs on a new requisition',
        }),

    # -- receiving report lifecycle -------------------------------------------
    Tuple_(
        'receiving_reports.models.COMMITTED_STATUSES', RR_COMMITTED,
        'receiving report',
        'do this receipt\'s lines consume their purchase-order line\'s open '
        'quantity?',
        {
            'draft':
                'a draft receipt records nothing yet; its own lines must not '
                'count against the order it is being built from',
            'submitted':
                'submitting commits nothing -- the receipt is with its '
                'approver, and approve() re-checks the open-quantity guard at '
                'the moment it does commit',
            'cancelled':
                'a cancelled receipt releases the order line\'s quantity, with '
                'no restore step to forget',
        }),
]


@pytest.mark.parametrize('t', REGISTRY, ids=repr)
def test_every_reachable_status_is_classified(t):
    """THE TEST. Each tuple must have an opinion about every status its
    document can reach -- in, out-with-a-reason, or a tracked gap."""
    reachable = statuses_written_by_the_app(DOCUMENTS[t.doc][0])
    unclassified = {s for s in reachable
                    if s not in t.members
                    and s not in t.excluded
                    and s not in t.known_gap}
    assert not unclassified, (
        '%s decides: %s\n'
        'These %s statuses are reachable in the app but appear neither in the '
        'tuple nor in its EXCLUDED_ON_PURPOSE: %s.\n'
        'Decide what each one means for that question and say so in one place '
        'or the other. Leaving one unclassified is exactly how a purchase '
        'order in `submitted` became invisible to the entire allocation '
        'system for weeks.'
        % (t.name, t.question, t.doc, sorted(unclassified)))


@pytest.mark.parametrize('t', REGISTRY, ids=repr)
def test_no_exclusion_names_a_status_that_no_longer_exists(t):
    """A lifecycle shrinks too. An exclusion for a status nothing writes any
    more is stale documentation that reads as a live decision."""
    reachable = statuses_written_by_the_app(DOCUMENTS[t.doc][0])
    stale = (set(t.excluded) | set(t.known_gap)) - reachable
    assert not stale, (
        '%s excludes %s, but nothing in the app assigns those %s statuses any '
        'more. Remove the entries -- a reason for a state that cannot happen '
        'is not a decision, it is drift.' % (t.name, sorted(stale), t.doc))


@pytest.mark.parametrize('t', REGISTRY, ids=repr)
def test_no_member_is_a_status_nothing_ever_writes(t):
    """A typo'd member is a filter that silently matches nothing -- a permanent
    no-op that reads as an active rule. `partially_received` is the one real
    case and is declared INERT with its reason."""
    reachable = statuses_written_by_the_app(DOCUMENTS[t.doc][0])
    unreachable = set(t.members) - reachable - set(INERT)
    assert not unreachable, (
        '%s contains %s, which nothing in the app ever assigns. Either it is a '
        'typo -- a member that silently matches no row -- or it is a real '
        'forward-looking entry, in which case add it to INERT with the reason.'
        % (t.name, sorted(unreachable)))


@pytest.mark.parametrize('t', REGISTRY, ids=repr)
def test_every_known_gap_carries_a_dated_finding(t):
    """A gap is tolerated debt, not a quiet exclusion. It must name when it was
    found, so it cannot be used to park an unclassified status indefinitely."""
    for status, note in t.known_gap.items():
        assert re.search(r'\b20\d\d-\d\d-\d\d\b', note), (
            '%s parks %r in known_gap without a dated finding. A gap with no '
            'date is an exclusion pretending to be a ticket -- either write '
            'the reason it is EXCLUDED_ON_PURPOSE, or record when and where '
            'the defect was found.' % (t.name, status))


# -- layer 3: is the registry itself complete? --------------------------------

#: How a status collection is consumed. Named collections only -- see the
#: module docstring's KNOWN LIMIT.
_CONSUMERS = (
    re.compile(r'\.status\.in_\(\s*([A-Za-z_][\w.]*)\s*[,)]'),
    re.compile(r'\.status\.notin_\(\s*([A-Za-z_][\w.]*)\s*[,)]'),
    re.compile(r'\.status\s+not\s+in\s+([A-Za-z_][\w.]*)'),
    re.compile(r'\.status\s+in\s+([A-Za-z_][\w.]*)'),
)


def status_collections_used_in_p2p():
    """Every NAMED status collection the purchase area filters or gates on."""
    found = set()
    for entry in P2P:
        target = APP / entry
        paths = [target] if target.is_file() else sorted(target.rglob('*.py'))
        for path in paths:
            text = path.read_text(encoding='utf-8')
            for pattern in _CONSUMERS:
                found |= set(pattern.findall(text))
    return found


def test_the_consumer_scrape_still_works():
    """GUARD ON THE GUARD. An empty or tiny result would make the completeness
    test below assert nothing at all."""
    found = status_collections_used_in_p2p()
    anchors = {'COMMITTED_PO', 'PULLABLE_PR', 'RECEIVABLE_PO_STATUSES'}
    assert anchors <= found, (
        'The consumer scrape no longer finds %s. It is not reading the '
        'purchase modules any more, so the registry-completeness test below is '
        'passing against an empty set.' % sorted(anchors - found))


def _registry_entries_matching(scraped):
    """Registry names ending in *scraped*.

    Source spells a collection however it is imported -- bare `COMMITTED_PO`,
    or dotted `PurchaseOrder.AMEND_STATUSES` -- while REGISTRY spells each one
    fully qualified so two same-named tuples in different modules stay
    distinguishable. Matched on the dotted suffix so both spellings meet, and
    the caller rejects an ambiguous match rather than picking one.
    """
    return [t.name for t in REGISTRY
            if t.name == scraped or t.name.endswith('.' + scraped)]


def test_every_status_collection_in_the_purchase_area_is_registered():
    """The registry is itself a hand-kept list, which is the thing this file
    distrusts. So it is checked against the source the same way the lifecycles
    are: a tuple added to the purchase area tomorrow fails here until somebody
    classifies it."""
    used = status_collections_used_in_p2p()
    unregistered = sorted(n for n in used if not _registry_entries_matching(n))
    assert not unregistered, (
        'These status collections are used to filter or gate a document in the '
        'purchase area but are not in REGISTRY: %s. Add each one with the '
        'question it answers and a reason for every status it leaves out. An '
        'unregistered tuple is exactly as invisible as an unclassified status.'
        % unregistered)


def test_no_registry_name_is_ambiguous():
    """Suffix matching is only safe while it is unique. Two entries whose names
    collide on the spelling the source uses would let one satisfy the
    completeness check on the other's behalf -- a registered-looking tuple that
    is never actually classified."""
    ambiguous = {n: _registry_entries_matching(n)
                 for n in status_collections_used_in_p2p()
                 if len(_registry_entries_matching(n)) > 1}
    assert not ambiguous, (
        'These source spellings match more than one REGISTRY entry: %s. '
        'Disambiguate at the call site (import the module, not the name) so '
        'each tuple is checked on its own.' % ambiguous)


def test_the_two_receivable_spellings_have_not_drifted():
    """`RECEIVABLE_PO_STATUSES` and `_RECEIVABLE_PO` are ONE rule -- which
    orders may still be received or billed against -- written twice, in two
    modules, with no import between them. Classified separately above because
    each must justify itself; pinned equal here because the day they disagree,
    a receipt and a bill will accept different orders and nothing else will
    say so."""
    assert tuple(RECEIVABLE_PO_STATUSES) == tuple(_RECEIVABLE_PO), (
        'receiving_reports.views.RECEIVABLE_PO_STATUSES is %r but '
        'purchase_billing._RECEIVABLE_PO is %r. These are two spellings of one '
        'rule; if the divergence is deliberate, delete this test and say why '
        'in both modules.' % (RECEIVABLE_PO_STATUSES, _RECEIVABLE_PO))
