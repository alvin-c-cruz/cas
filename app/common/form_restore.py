"""Give a document's line items back when its save is REFUSED.

One defect, found four times: a create view re-renders a rejection with a
hardcoded empty list and silently throws away the lines the POST is already
carrying. Sales Orders (2026-08-05), Purchase Orders (2026-08-30, after it
deterministically blocked a real purchaser for weeks), and now Purchase
Requisitions and Bills of Materials.

It lives here rather than in each module because the next port is Quotations,
and three private copies of one rule is how the spellings drift -- which is the
same shape as the sweep failure that let it survive: the 2026-08-05 fix swept the
sales-side FAMILY rather than the repo, and `grep -rn "line_items=\\[\\]" app/`
was never run.

THE TRAP THIS FUNCTION EXISTS TO CARRY: the two ends of the round trip can spell
the unit differently. The purchase_orders and purchase_requests forms serialise
`uom_id`, while their row renderers read `unit_of_measure_id` (what `to_dict()`
emits). Restoring a payload verbatim therefore hands every line back with an
EMPTY unit -- products and quantities kept, every UoM re-picked by hand. That
half was invisible to the tests written for the Purchase Order fix and was found
only by driving a browser; it is normalised HERE so a future port cannot miss it.

Bills of Materials do NOT need that translation -- their form both writes and
reads `uom_id` -- which is why it is a parameter rather than unconditional.
Applying it there would invent a key the renderer never looks at.
"""
import json


def restore_posted_lines(raw, normalise_uom=True):
    """Parse a POSTed line payload into the shape the row renderer reads back.

    `raw` is the raw form value (``request.form.get('line_items', '[]')``), not a
    parsed object -- callers hand over exactly what the request carried.

    A fresh GET needs no special case: ``request.form`` is empty on a GET, so the
    caller's ``'[]'`` default is what parses, and a brand-new form comes back
    empty. Do NOT add a ``request.method == 'GET'`` guard for it -- one was tried
    on the Purchase Order fix and removed, because no test could distinguish it
    from its absence and a branch nothing can pin is a branch that breaks
    silently.

    The unit key is filled only when ABSENT, so a payload already in the
    renderer's spelling (an edit view's GET path, straight off ``to_dict()``) stays
    authoritative, and a services line with no UoM master id is never handed a
    fabricated one -- that would bind it to whatever unit happens to hold that row.
    """
    items = json.loads(raw or '[]')
    if not normalise_uom:
        return items
    for d in items:
        if not isinstance(d, dict):
            continue
        if d.get('unit_of_measure_id') is None and d.get('uom_id') is not None:
            d['unit_of_measure_id'] = d['uom_id']
    return items
