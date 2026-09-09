"""How much of a requisition line is already on order.

DERIVED, never stored. The answer is always a SUM over the purchase-order lines
that point at the requisition line, so cancelling or voiding a PO reopens its
lines with no restore step to forget.

This mirrors receiving_reports.models.po_line_open_qty deliberately. The stored
alternative already exists in this codebase and is dead:
PurchaseOrderItem.received_quantity and .billed_quantity are declared columns
that nothing ever assigns.
"""
from decimal import Decimal

from app import db

#: Every PO status except 'cancelled'. Draft counts on purpose -- a line pulled
#: onto a draft is spoken for, so two buyers cannot both claim it. `submitted`
#: counts for the same reason, with more force: that order has already been
#: handed to an approver.
#:
#: `submitted` was MISSING here until 2026-08-26
#: (BUG-SUBMITTED-PO-NOT-COUNTED-IN-PR-ALLOCATION). It arrived with the purchase
#: order's submit step (cas 579e12ed) and this tuple, written when
#: draft -> approved was the entire lifecycle, was never widened -- so a
#: requisition line fully ordered on a submitted order was offered again at its
#: full original quantity, and accepting it ordered 20 against a requisition for
#: 10 with nothing refusing it.
#:
#: THIS TUPLE IS THE ONLY THING that decides whether a purchase-order line is
#: spoken for. Exactly two functions read it -- pr_line_ordered_qty and
#: _has_committed_reference -- and the picker (open_lines_for_branch), the
#: save-time ceiling (assert_payload_within_open_qty) and recompute_pr_status all
#: derive from those. A status missing here is therefore invisible to the whole
#: allocation system at once, on BOTH doors: it is why the two-door guard from
#: cas 5892bf0a did not help, since both doors read this same input.
#:
#: Adding a status to the purchase order's lifecycle? Classify it here or in
#: tests/unit/test_lifecycle_tuples_are_classified.py, in this tuple's own
#: REGISTRY entry. That test scrapes the real writers out of the source and
#: fails until the decision is made, because leaving one unclassified is
#: precisely how this happened. It guards the nine sibling tuples the same way
#: -- PULLABLE_PR and RECOMPUTABLE_PR below included.
#:
#: ('partially_received' is inert -- nothing in the app writes it. Kept because
#: removing it would change behaviour only if something started to.)
COMMITTED_PO = ('draft', 'submitted', 'approved', 'partially_received', 'closed')


def pr_line_ordered_qty(pr_item, exclude_po_id=None):
    """Total quantity committed PO lines have ordered against *pr_item*.

    Pass *exclude_po_id* to leave one purchase order out of the sum -- the draft
    being edited must not count its own lines against itself.
    """
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    q = (db.session.query(db.func.coalesce(db.func.sum(PurchaseOrderItem.quantity), 0))
         .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
         .filter(PurchaseOrderItem.source_pr_item_id == pr_item.id)
         .filter(PurchaseOrder.status.in_(COMMITTED_PO)))
    if exclude_po_id is not None:
        q = q.filter(PurchaseOrder.id != exclude_po_id)
    return Decimal(str(q.scalar() or 0))


def pr_line_received_qty(pr_item):
    """Total quantity committed RECEIVING REPORTS have delivered against *pr_item*.

    Two hops, because a requisition is never received directly: the requisition
    line is ordered onto PO lines (`source_pr_item_id`), and those PO lines are
    received by RR lines (`purchase_order_item_id`). One query walks both.

    Only RR statuses in receiving_reports.models.COMMITTED_STATUSES
    ('approved', 'billed') count, exactly as po_line_open_qty does -- a draft or
    cancelled receipt has delivered nothing, and counting it would report a
    requisition as delivered on the strength of an unapproved document.

    Mirrors pr_line_ordered_qty's shape and return type (always a Decimal, never
    None) so the two can be compared without normalising either.
    """
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    # Imported under its CANONICAL name, not aliased: the lifecycle-tuple guard
    # scrapes the purchase area for named status collections and matches them to
    # its REGISTRY by name, so an alias reads as an eleventh, unregistered tuple.
    # (COMMITTED_PO above is this module's own; the two never collide in scope.)
    from app.receiving_reports.models import (
        COMMITTED_STATUSES, ReceivingReport, ReceivingReportItem)
    q = (db.session.query(db.func.coalesce(db.func.sum(ReceivingReportItem.received_quantity), 0))
         .join(ReceivingReport, ReceivingReportItem.receiving_report_id == ReceivingReport.id)
         .join(PurchaseOrderItem,
               ReceivingReportItem.purchase_order_item_id == PurchaseOrderItem.id)
         .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
         .filter(PurchaseOrderItem.source_pr_item_id == pr_item.id)
         .filter(PurchaseOrder.status.in_(COMMITTED_PO))
         .filter(ReceivingReport.status.in_(COMMITTED_STATUSES)))
    return Decimal(str(q.scalar() or 0))


def pr_line_is_fully_received(pr_item):
    """Has this requisition line been delivered in full?

    Measured against what the REQUISITION asked for, not what was ordered: the
    requisition's own question is "did I get what I asked for?", and an order
    raised for less than the requested quantity has not answered it. A line
    carrying no quantity (LINE_QUANTITY_REQUIRED is False) can never be proven
    fully received, so it reads False rather than vacuously True.
    """
    requested = pr_item.quantity
    if requested is None:
        return False
    requested = Decimal(str(requested))
    if requested <= 0:
        return False
    return pr_line_received_qty(pr_item) >= requested


def pr_line_open_qty(pr_item, exclude_po_id=None):
    """Requested minus ordered, or None when the line carries no quantity.

    None is not "zero open" -- it means there is no ceiling to enforce. A
    requisition line may legitimately have no quantity
    (PurchaseRequest.LINE_QUANTITY_REQUIRED is False).
    """
    if pr_item.quantity is None:
        return None
    return Decimal(str(pr_item.quantity)) - pr_line_ordered_qty(pr_item, exclude_po_id)


def pr_line_is_open(pr_item, exclude_po_id=None):
    """True when the line still needs ordering.

    The status rules are written over THIS, not over quantities, because a
    quantity comparison says nothing about an unquantified line. For those the
    test is boolean: open until any committed PO line references it.
    """
    if pr_item.quantity is None:
        return pr_line_ordered_qty(pr_item, exclude_po_id) == Decimal('0') and \
            not _has_committed_reference(pr_item, exclude_po_id)
    return pr_line_open_qty(pr_item, exclude_po_id) > Decimal('0')


def _has_committed_reference(pr_item, exclude_po_id=None):
    """Whether ANY committed PO line points at this requisition line.

    Separate from the quantity sum because a PO line may reference an
    unquantified requisition line while itself carrying a quantity of zero or
    None, which would sum to nothing and read as untouched.
    """
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    q = (db.session.query(PurchaseOrderItem.id)
         .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
         .filter(PurchaseOrderItem.source_pr_item_id == pr_item.id)
         .filter(PurchaseOrder.status.in_(COMMITTED_PO)))
    if exclude_po_id is not None:
        q = q.filter(PurchaseOrder.id != exclude_po_id)
    return q.first() is not None


#: Requisition statuses whose lines may be pulled onto a purchase order.
#:
#: `submitted` was added 2026-08-26 by owner decision so a staff purchaser can
#: prepare the purchase order while the requisition is still with its approver
#: -- the wait was for a signature, not for information.
#:
#: THE APPROVAL CONTROL DID NOT MOVE INTO THIS TUPLE. It moved to purchase-order
#: APPROVAL, via unapproved_source_prs() below: pulling is data entry, submit is
#: how a staff purchaser hands the order on, and approval is the control. Note
#: what is deliberately still absent -- `draft` (nobody has been handed it yet),
#: and `rejected`/`cancelled`, which are the two exits FROM submitted and so the
#: statuses this widening is most likely to leak into.
#:
#: RECOMPUTABLE_PR was deliberately NOT widened to match. See its own note.
#: `partially_received` is here for a LOAD-BEARING reason: since delivery
#: outranks ordering (2026-09-06), a requisition that is only PARTLY ordered
#: becomes `partially_received` the moment anything arrives. Omitting it would
#: make the rest of that requisition unorderable -- the buyer could no longer
#: raise the order for the lines still outstanding. `received` is excluded
#: because every line is delivered in full, so there is nothing left to pull.
PULLABLE_PR = ('submitted', 'approved', 'partially_converted',
               'partially_received')

#: Requisition statuses that count as APPROVED when releasing a purchase order.
#:
#: NOT `status == 'approved'`. `partially_converted` and `converted` are
#: POST-approval states -- a requisition reaches either one only by being
#: approved and then ordered against -- so reading them as unapproved would
#: block the SECOND purchase order raised against a partially ordered
#: requisition, which is the ordinary case partial allocation exists to serve.
#:
#: Decided on STATUS rather than on `approved_at is not None` because cancel()
#: accepts an already-approved requisition: a cancelled one can carry a real
#: approved_at while its demand has been withdrawn.
#: `partially_received` and `received` are post-approval states by
#: construction: recompute_pr_status can only reach them from approved /
#: partially_converted / converted (RECOMPUTABLE_PR excludes submitted), so a
#: requisition cannot be delivered without having been approved first. Reading
#: them as unapproved would block a purchase order raised against a requisition
#: whose earlier lines have already arrived.
APPROVED_PR = ('approved', 'partially_converted', 'converted',
               'partially_received', 'received')


def unapproved_source_prs(po):
    """The distinct requisitions behind *po*'s lines that are NOT yet approved.

    ONE query, and the ONE predicate behind the owner decision of 2026-08-26: a
    submitted requisition may be pulled onto a draft purchase order so a staff
    purchaser can prepare the order early, but that order may not be APPROVED
    until every requisition feeding it has been.

    Deliberately one predicate rather than separate guards on submitted /
    rejected / cancelled sources. Those are one rule -- "the demand behind this
    line was never authorised" -- and three spellings of one rule is how three
    guards drift apart. Asked at approval, not at pull and not at submit:
    pulling is data entry, submit is how a staff purchaser hands the order on,
    and approval is the control.

    Does NOT filter on the purchase order's own status, unlike every allocation
    sum in this module. Those ask what QUANTITY is spoken for and must therefore
    ignore cancelled orders; this asks about THIS order's own lines, so
    COMMITTED_PO has no bearing on it. Reusing that tuple here is the
    obvious-looking wrong move, and `test_a_cancelled_purchase_order_is_still_measured`
    pins it.

    Ordered by requisition number so a refusal message naming several does not
    reshuffle between identical attempts and read as a different problem.

    The `.distinct()` is belt-and-braces, and measured as such: deleting it
    leaves every test green, because `Query.all()` over a single full entity
    already collapses duplicate rows through the identity map. It is kept so the
    guarantee survives a rewrite to `select()` + `session.scalars()`, where that
    implicit dedup does NOT apply and `.unique()` becomes mandatory. Neither
    mechanism is observable alone, which is why the test pins the RESULT -- one
    requisition appears once -- rather than claiming to pin this clause.
    """
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrderItem
    return (db.session.query(PurchaseRequest)
            .join(PurchaseRequestItem,
                  PurchaseRequestItem.purchase_request_id == PurchaseRequest.id)
            .join(PurchaseOrderItem,
                  PurchaseOrderItem.source_pr_item_id == PurchaseRequestItem.id)
            .filter(PurchaseOrderItem.purchase_order_id == po.id)
            .filter(PurchaseRequest.status.notin_(APPROVED_PR))
            .order_by(PurchaseRequest.pr_number.asc())
            .distinct()
            .all())


def po_links_for_pr_ids(pr_ids):
    """``{pr_id: [(po_id, po_number), ...]}`` -- the purchase orders each
    requisition's LINES have been pulled onto.

    ONE query for a whole page, mirroring pr_ids_blocked_by_pending_amendment.
    A per-requisition property would be N+1 on the list.

    NOT `PurchaseRequest.purchase_order_id`. That header FK is set only by
    convert() -- its own comment calls it "a back-link to the most recent PO" --
    so a requisition reaching an order through the FORM'S PICKER never sets it
    and read as unordered (BUG-PR-PO-COLUMN-READS-HEADER-FK-NOT-LINE-LINKS).
    Since 2026-08-26 that is the ORDINARY case: PULLABLE_PR admits `submitted`
    while convert() still refuses anything not approved, so for a submitted
    requisition the FK cannot be set at all.

    Reading the line links instead is a strict SUPERSET, not an alternative:
    convert() also stamps `source_pr_item_id` on every line it builds, so the
    shortcut path is covered here too and the FK needs no fallback.

    Filtered by COMMITTED_PO for the same reason every allocation sum is --
    cancelling an order releases its lines, so a cancelled order must not be
    named as the destination of a requisition that is once again open.

    Ordered by po_number so a requisition split across several orders lists them
    the same way twice running.
    """
    from app.purchase_requests.models import PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    ids = [i for i in (pr_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (db.session.query(PurchaseRequestItem.purchase_request_id,
                             PurchaseOrder.id, PurchaseOrder.po_number)
            .join(PurchaseOrderItem,
                  PurchaseOrderItem.source_pr_item_id == PurchaseRequestItem.id)
            .join(PurchaseOrder,
                  PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .filter(PurchaseRequestItem.purchase_request_id.in_(ids))
            .filter(PurchaseOrder.status.in_(COMMITTED_PO))
            .order_by(PurchaseOrder.po_number.asc())
            .distinct()
            .all())
    out = {}
    for pr_id, po_id, po_number in rows:
        # distinct() is on the whole row, so one order feeding TWO lines of the
        # same requisition arrives twice -- dedup on the order itself.
        seen = out.setdefault(pr_id, [])
        if (po_id, po_number) not in seen:
            seen.append((po_id, po_number))
    return out


def pr_ids_blocked_by_pending_amendment(pr_ids=None):
    """Requisitions that may NOT be pulled from because an amendment request is
    awaiting review (owner decision, 2026-08-20).

    ONE query. Pass `pr_ids` to scope it; omit for every pending request.

    Status alone cannot express this: an `approved` requisition with a pending
    request is still `approved`, which is why PULLABLE_PR did not catch it and
    the PO form pulled PR 00001 while the shortcut route refused it
    (BUG-PENDING-AMENDMENT-BLOCK-BYPASSED-BY-THE-PO-FORM).
    """
    from app.purchase_requests.amendment_models import PurchaseRequestAmendmentRequest
    q = (db.session.query(PurchaseRequestAmendmentRequest.purchase_request_id)
         .filter(PurchaseRequestAmendmentRequest.status ==
                 PurchaseRequestAmendmentRequest.STATUS_PENDING))
    if pr_ids is not None:
        ids = [i for i in pr_ids if i is not None]
        if not ids:
            return set()
        q = q.filter(PurchaseRequestAmendmentRequest.purchase_request_id.in_(ids))
    return {r[0] for r in q.distinct().all()}


def assert_no_pending_amendment(allocations):
    """Refuse a submitted payload that pulls from a requisition under amendment.

    The picker already hides these, but hiding an option is not enforcing a rule
    -- a hand-posted `source_pr_item_id` reaches the same code path. Same
    two-layer shape the AP employee-payee fix proved (cas afa15b8a).

    Deliberately NOT folded into assert_payload_within_open_qty: that function is
    shared with Receiving Reports, which allocate against PURCHASE ORDERS and
    have nothing to do with requisition amendments.
    """
    blocked = pr_ids_blocked_by_pending_amendment(
        [pr_item.purchase_request_id for pr_item, _qty, _idx in allocations])
    if not blocked:
        return
    for pr_item, _qty, idx in allocations:
        if pr_item.purchase_request_id in blocked:
            pr = pr_item.purchase_request
            raise ValueError(
                'Line %d: Purchase Requisition "%s" has an amendment request '
                'awaiting review and cannot be ordered until it is approved or '
                'rejected.' % (idx, pr.pr_number if pr else '(unknown)'))


def _pr_item_label(pr_item):
    """How a requisition line is named in a refusal message."""
    return (pr_item.product.name if pr_item.product
            else (pr_item.description or 'this item'))


def assert_payload_within_open_qty(allocations, exclude_po_id=None):
    """Refuse a SUBMITTED PAYLOAD that orders more of a requisition line than
    remains open, counting every line of that payload TOGETHER.

    *allocations* is an ordered iterable of ``(pr_item, qty, idx)`` triples --
    one per submitted line that names a requisition line, in submission order.
    *idx* is that line's 1-based position, used only in the message.

    THE CEILING BELONGS TO THE REQUISITION LINE, NOT TO A PURCHASE-ORDER LINE.
    pr_line_open_qty() sums the PO lines already COMMITTED IN THE DATABASE, so
    nothing in the submission being validated counts towards it. Asking the
    question once per submitted line therefore measured every line against the
    FULL open quantity: the same requisition line pulled twice into one order
    answered "20 <= 20" twice and shipped 40 against 20 open
    (BUG-PR-PO-CEILING-NOT-AGGREGATED-WITHIN-ONE-SUBMISSION). Only the payload's
    per-requisition-line TOTAL is comparable to the ceiling.

    Summed up front and checked ONCE per distinct requisition line, rather than
    by threading a running tally through the caller's per-line loop: the message
    then names the requisition line that is over-ordered and every submitted line
    contributing to it, instead of whichever line happened to tip it over. It
    also means nothing is written before the whole submission is known to fit.

    Refuses at the FIRST over-ordered requisition line in submission order (dicts
    preserve insertion order), so the message is deterministic rather than
    dependent on id ordering.

    An unquantified requisition line has no ceiling, so there is nothing to
    check -- see pr_line_open_qty's None.
    """
    totals = {}
    for pr_item, qty, idx in allocations:
        # Keyed on pr_item.id, not on the instance: the caller resolves each
        # submitted line separately, and two db.session.get() calls for one id
        # need not hand back the same object once the identity map is bypassed.
        slot = totals.setdefault(pr_item.id, [pr_item, Decimal('0'), []])
        slot[1] += Decimal(str(qty or 0))
        slot[2].append(idx)

    for pr_item, total, idxs in totals.values():
        open_qty = pr_line_open_qty(pr_item, exclude_po_id)
        if open_qty is None:
            continue
        if total > open_qty:
            label = _pr_item_label(pr_item)
            if len(idxs) == 1:
                raise ValueError(
                    f'Line {idxs[0]}: only {open_qty} of {label} remain unordered.')
            lines = ', '.join(str(i) for i in idxs)
            raise ValueError(
                f'Lines {lines}: only {open_qty} of {label} remain unordered, '
                f'but these lines order {total} between them.')
    return None


def assert_within_open_qty(pr_item, qty, idx, exclude_po_id=None):
    """Refuse to order more of a requisition line than remains open, ONE line at
    a time.

    Enforced at save rather than by the picker's `max` attribute -- a POST
    bypasses the input entirely. *idx* is the submitted line's 1-based position,
    used only in the message.

    Delegates so there is exactly ONE implementation of the rule: a payload of
    one line is the single-line case, and a second hand-written spelling of a
    ceiling is how the two paths would drift. THIS ENTRY POINT IS NOT SUFFICIENT
    ON ITS OWN for validating a submission -- see assert_payload_within_open_qty,
    which is what a caller holding a whole line array must use.
    """
    return assert_payload_within_open_qty([(pr_item, qty, idx)],
                                          exclude_po_id=exclude_po_id)


def open_lines_for_branch(branch_id, exclude_po_id=None):
    """Every still-open requisition line in *branch_id*, for the PO picker.

    Quantities are returned as STRINGS, not floats: they are Numeric(15, 4) and
    round-tripping them through float would misreport 0.5555 in the very
    column the buyer types into.
    """
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    prs = (PurchaseRequest.query
           .filter(PurchaseRequest.branch_id == branch_id,
                   PurchaseRequest.status.in_(PULLABLE_PR))
           .order_by(PurchaseRequest.request_date.asc(), PurchaseRequest.id.asc())
           .all())
    # A pending amendment request blocks ordering, and status cannot say so --
    # the requisition is still `approved`. Resolved ONCE for the whole set, not
    # per requisition.
    blocked = pr_ids_blocked_by_pending_amendment([pr.id for pr in prs])
    prs = [pr for pr in prs if pr.id not in blocked]
    out = []
    for pr in prs:
        for li in pr.line_items:
            if not pr_line_is_open(li, exclude_po_id):
                continue
            open_qty = pr_line_open_qty(li, exclude_po_id)
            out.append({
                'pr_item_id': li.id,
                'pr_id': pr.id,
                'pr_number': pr.pr_number,
                # The picker offers `submitted` requisitions alongside approved
                # ones (2026-08-26), and the two are otherwise indistinguishable
                # in the modal. Without this the buyer only learns the demand was
                # never authorised at PO approval -- after building and pricing
                # the whole order. Rendered as a chip, not as a filter: pulling
                # early is the POINT, so the row stays offered.
                'pr_status': pr.status,
                'date_needed': pr.date_needed.isoformat() if pr.date_needed else None,
                'date_needed_asap': bool(pr.date_needed_asap),
                'product_id': li.product_id,
                'product_name': li.product.name if li.product else None,
                'description': li.description,
                'uom_id': li.unit_of_measure_id,
                'uom_code': (li.unit_of_measure.code if li.unit_of_measure
                             else li.uom_text),
                'requested': _qty_str(li.quantity),
                'ordered': _qty_str(pr_line_ordered_qty(li, exclude_po_id)),
                'open': _qty_str(open_qty),
            })
    return out


def _qty_str(v):
    """Numeric(15, 4) as a trimmed string: '20', '12.5', '' for None."""
    if v is None:
        return ''
    return '{:f}'.format(Decimal(str(v)).normalize())


#: Statuses recompute_pr_status may move between. A draft, submitted, cancelled
#: or rejected requisition is left exactly as it is.
#:
#: For draft, cancelled and rejected the reason is the original one: nothing can
#: order against them, and resurrecting a cancelled requisition would be a real
#: defect.
#:
#: `submitted` IS now orderable (PULLABLE_PR admits it since 2026-08-26) and is
#: kept out ANYWAY -- this is the load-bearing half of that change, not an
#: oversight. approve() and reject() both require `status == 'submitted'`
#: exactly. Recomputing a pulled requisition would move it to
#: partially_converted or converted, at which point it can no longer be approved
#: OR rejected: the approval step would vanish silently, leaving an unauthorised
#: requisition looking like a completed one. A pulled requisition therefore
#: stays `submitted` and settles to its true status when approve() recomputes it
#: -- which is why approve() calls recompute_pr_status BEFORE writing its Rev 0
#: baseline.
#:
#: `tests/unit/test_pr_allocation_rules.py::TestRecomputableExcludesSubmitted`
#: fails if anyone widens this to match PULLABLE_PR.
#: `partially_received` and `received` are here for the same reason `converted`
#: is: recompute is self-repairing, so a requisition must be able to move BACK
#: when a receiving report is cancelled or an order is withdrawn. Omitting them
#: would freeze a delivered requisition at its high-water mark -- the exact
#: counter-based failure the recompute-from-source design exists to avoid.
#: `submitted` joined this on 2026-09-06. It was previously excluded because
#: approve() and reject() required status == 'submitted' EXACTLY, so recomputing
#: a pulled requisition deleted its approval step. That coupling is gone --
#: both now read PurchaseRequest.awaiting_approval (approved_by_id), so a
#: requisition can be partially ordered AND still awaiting signature, which is
#: exactly what a requisition pulled before approval is.
RECOMPUTABLE_PR = ('submitted', 'approved', 'partially_converted', 'converted',
                   'partially_received', 'received')


def recompute_pr_status(pr):
    """Set and return the requisition's status from its lines' open state.

    Recompute-from-source: this never reads pr.status to decide the answer, so
    it is idempotent and self-repairing. A counter-based design cannot make
    that claim -- one missed decrement is permanent.

    Does NOT commit; the caller owns the transaction.
    """
    if pr.status not in RECOMPUTABLE_PR:
        return pr.status
    # `approved` is the resting state of a requisition with nothing ordered
    # against it -- but ONLY once it has actually been approved. Writing it for
    # an unsigned requisition would approve it silently, which is precisely the
    # hazard that kept `submitted` out of RECOMPUTABLE_PR until the approval fact
    # was decoupled from the status.
    idle = 'submitted' if pr.awaiting_approval else 'approved'
    lines = list(pr.line_items)
    if not lines:
        pr.status = idle
        return pr.status
    open_count = sum(1 for li in lines if pr_line_is_open(li))
    untouched = sum(1 for li in lines
                    if pr_line_ordered_qty(li) == Decimal('0')
                    and not _has_committed_reference(li))
    if untouched == len(lines):
        pr.status = idle
        return pr.status

    # DELIVERY OUTRANKS ORDERING once anything has actually arrived (owner
    # request 2026-09-06: "this status must change when the PR is partially or
    # fully delivered via the RR document").
    #
    # Ordering is a promise; receiving is the fact. A requisition that is only
    # PARTLY ordered but already partly delivered reads `partially_received`
    # rather than `partially_converted` -- reporting the promise while goods are
    # on the shelf is the less useful of the two answers, and the requisition's
    # own question is "did I get what I asked for?".
    #
    # `received` therefore requires EVERY line delivered in full against the
    # REQUESTED quantity, which is strictly stronger than `converted` (every
    # line fully ordered): a requisition cannot be fully received without having
    # been fully ordered first.
    received_lines = sum(1 for li in lines if pr_line_is_fully_received(li))
    any_received = any(pr_line_received_qty(li) > Decimal('0') for li in lines)
    if received_lines == len(lines):
        pr.status = 'received'
    elif any_received:
        pr.status = 'partially_received'
    elif open_count == 0:
        pr.status = 'converted'
    else:
        pr.status = 'partially_converted'
    return pr.status


def rr_links_for_pr_ids(pr_ids):
    """``{pr_id: [(rr_id, rr_number), ...]}`` -- the receiving reports that have
    delivered against each requisition's lines.

    Two hops, the same walk pr_line_received_qty makes: requisition line -> PO
    line (`source_pr_item_id`) -> RR line (`purchase_order_item_id`). ONE query
    for a whole page, mirroring po_links_for_pr_ids; a per-requisition property
    would be N+1 on the list.

    Filtered by COMMITTED_STATUSES, not merely "not cancelled": a draft or
    submitted receipt has delivered nothing, and naming it here would tell the
    reader goods had arrived on the strength of an unapproved document.
    """
    from app.purchase_requests.models import PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrderItem
    from app.receiving_reports.models import (
        COMMITTED_STATUSES, ReceivingReport, ReceivingReportItem)
    ids = [i for i in (pr_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (db.session.query(PurchaseRequestItem.purchase_request_id,
                             ReceivingReport.id, ReceivingReport.rr_number)
            .join(PurchaseOrderItem,
                  PurchaseOrderItem.source_pr_item_id == PurchaseRequestItem.id)
            .join(ReceivingReportItem,
                  ReceivingReportItem.purchase_order_item_id == PurchaseOrderItem.id)
            .join(ReceivingReport,
                  ReceivingReport.id == ReceivingReportItem.receiving_report_id)
            .filter(PurchaseRequestItem.purchase_request_id.in_(ids))
            .filter(ReceivingReport.status.in_(COMMITTED_STATUSES))
            .order_by(ReceivingReport.rr_number.asc())
            .distinct()
            .all())
    return _dedup_links(rows)


def ap_links_for_pr_ids(pr_ids):
    """``{pr_id: [(ap_id, ap_number), ...]}`` -- the bills raised for the goods
    this requisition asked for.

    Third hop: the billing link is `ReceivingReport.accounts_payable_id`, so a
    requisition is billed only through a receipt. A bill keyed straight to a
    purchase order with no receipt is therefore invisible here, which is correct
    for this column -- it answers "what happened to MY goods", and goods that
    were never received were never delivered against this requisition.
    """
    from app.purchase_requests.models import PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrderItem
    from app.receiving_reports.models import (
        COMMITTED_STATUSES, ReceivingReport, ReceivingReportItem)
    from app.accounts_payable.models import AccountsPayable
    ids = [i for i in (pr_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (db.session.query(PurchaseRequestItem.purchase_request_id,
                             AccountsPayable.id, AccountsPayable.ap_number)
            .join(PurchaseOrderItem,
                  PurchaseOrderItem.source_pr_item_id == PurchaseRequestItem.id)
            .join(ReceivingReportItem,
                  ReceivingReportItem.purchase_order_item_id == PurchaseOrderItem.id)
            .join(ReceivingReport,
                  ReceivingReport.id == ReceivingReportItem.receiving_report_id)
            .join(AccountsPayable,
                  AccountsPayable.id == ReceivingReport.accounts_payable_id)
            .filter(PurchaseRequestItem.purchase_request_id.in_(ids))
            .filter(ReceivingReport.status.in_(COMMITTED_STATUSES))
            .order_by(AccountsPayable.ap_number.asc())
            .distinct()
            .all())
    return _dedup_links(rows)


def cd_links_for_pr_ids(pr_ids):
    """``{pr_id: [(cd_id, cd_number), ...]}`` -- the disbursements that paid the
    bills for this requisition's goods.

    Fourth and last hop: a cash disbursement LINE carries `ap_id`, so payment is
    reached through the bill, which is reached through the receipt. The whole
    chain in one query rather than four round trips per row.
    """
    from app.purchase_requests.models import PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrderItem
    from app.receiving_reports.models import (
        COMMITTED_STATUSES, ReceivingReport, ReceivingReportItem)
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
    ids = [i for i in (pr_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (db.session.query(PurchaseRequestItem.purchase_request_id,
                             CashDisbursementVoucher.id,
                             CashDisbursementVoucher.cdv_number)
            .join(PurchaseOrderItem,
                  PurchaseOrderItem.source_pr_item_id == PurchaseRequestItem.id)
            .join(ReceivingReportItem,
                  ReceivingReportItem.purchase_order_item_id == PurchaseOrderItem.id)
            .join(ReceivingReport,
                  ReceivingReport.id == ReceivingReportItem.receiving_report_id)
            .join(AccountsPayable,
                  AccountsPayable.id == ReceivingReport.accounts_payable_id)
            .join(CDVApLine, CDVApLine.ap_id == AccountsPayable.id)
            .join(CashDisbursementVoucher,
                  CashDisbursementVoucher.id == CDVApLine.cdv_id)
            .filter(PurchaseRequestItem.purchase_request_id.in_(ids))
            .filter(ReceivingReport.status.in_(COMMITTED_STATUSES))
            .order_by(CashDisbursementVoucher.cdv_number.asc())
            .distinct()
            .all())
    return _dedup_links(rows)


def _dedup_links(rows):
    """``[(pr_id, doc_id, doc_number), ...]`` -> ``{pr_id: [(doc_id, number)]}``.

    distinct() is on the whole row, so one document feeding TWO lines of the
    same requisition arrives twice -- dedup on the document itself. Shared by
    the three link helpers above so the three cannot drift apart.
    """
    out = {}
    for pr_id, doc_id, doc_number in rows:
        seen = out.setdefault(pr_id, [])
        if (doc_id, doc_number) not in seen:
            seen.append((doc_id, doc_number))
    return out


def po_links_for_pr_items(pr_item_ids):
    """``{pr_item_id: [(po_id, po_number), ...]}`` -- per LINE, not per document.

    The list page's po_links_for_pr_ids answers "which orders is this
    requisition on"; the detail page's allocation panel needs "which order is
    THIS LINE on", because a requisition split across two orders is exactly the
    case the panel exists to show. One query for the whole panel.
    """
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    ids = [i for i in (pr_item_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (db.session.query(PurchaseOrderItem.source_pr_item_id,
                             PurchaseOrder.id, PurchaseOrder.po_number)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .filter(PurchaseOrderItem.source_pr_item_id.in_(ids))
            .filter(PurchaseOrder.status.in_(COMMITTED_PO))
            .order_by(PurchaseOrder.po_number.asc())
            .distinct()
            .all())
    return _dedup_links(rows)


def rr_links_for_pr_items(pr_item_ids):
    """``{pr_item_id: [(rr_id, rr_number), ...]}`` -- per LINE.

    Same two hops as pr_line_received_qty, and filtered the same way: only
    COMMITTED_STATUSES receipts are named, so a draft receipt never reports goods
    as delivered against a requisition line.
    """
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from app.receiving_reports.models import (
        COMMITTED_STATUSES, ReceivingReport, ReceivingReportItem)
    ids = [i for i in (pr_item_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (db.session.query(PurchaseOrderItem.source_pr_item_id,
                             ReceivingReport.id, ReceivingReport.rr_number)
            .join(ReceivingReportItem,
                  ReceivingReportItem.purchase_order_item_id == PurchaseOrderItem.id)
            .join(ReceivingReport,
                  ReceivingReport.id == ReceivingReportItem.receiving_report_id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .filter(PurchaseOrderItem.source_pr_item_id.in_(ids))
            .filter(PurchaseOrder.status.in_(COMMITTED_PO))
            .filter(ReceivingReport.status.in_(COMMITTED_STATUSES))
            .order_by(ReceivingReport.rr_number.asc())
            .distinct()
            .all())
    return _dedup_links(rows)


def allocation_panel_rows(pr):
    """One row per requisition line: what was asked, ordered, received, and what
    is STILL OUTSTANDING -- with the documents that account for each.

    Answers the question the requisition itself cannot: "is there anything here
    still waiting to be ordered, and where did the rest go?" (owner request
    2026-09-06).

    Three queries for the whole panel regardless of line count -- the two link
    maps plus whatever the quantity helpers do -- rather than a property read per
    row, which is how the list page's N+1 was avoided too.

    `open_qty` is None for a line carrying no quantity: there is no ceiling to
    measure against, and printing 0 there would read as "nothing outstanding"
    when the truth is "unknown". The template says so rather than showing a
    number.
    """
    lines = sorted(pr.line_items, key=lambda li: (li.line_number or 0))
    ids = [li.id for li in lines]
    po_map = po_links_for_pr_items(ids)
    rr_map = rr_links_for_pr_items(ids)
    rows = []
    for li in lines:
        ordered = pr_line_ordered_qty(li)
        received = pr_line_received_qty(li)
        rows.append({
            'line': li,
            'requested': li.quantity,
            'ordered': ordered,
            'received': received,
            'open_qty': pr_line_open_qty(li),
            'is_open': pr_line_is_open(li),
            'fully_received': pr_line_is_fully_received(li),
            'po_links': po_map.get(li.id, []),
            'rr_links': rr_map.get(li.id, []),
        })
    return rows
