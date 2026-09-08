"""Build an AP voucher's Notes (Particulars) from the PO/RR pulled into it.

The AP form refuses to save with Notes empty, so the text was being retyped by
hand on every voucher even though the pulled documents already carry every fact
it states.

The sentence is not invented. It reproduces the convention measured across the
1353 particulars in PhilGen's legacy disbursement register:

    PAYMENT FOR THE PURCHASE OF <what>
    FOR <purpose> USE
    -PO NO.00742, SI NO.403159, RR - OCTOBER 2025

Everything here is a pure function of documents already in the database, which
is why it lives server-side rather than in the pull script: it is business
wording, and this way it is unit-testable and the browser only has to drop the
returned string into a textarea.

The governing rule throughout is NEVER INVENT. No documents means an empty
string, not a dangling "PAYMENT FOR THE PURCHASE OF" that the form's own
non-empty guard would happily accept. A missing purpose or invoice number means
that part is left out, not filled with a placeholder -- every purchase order
that exists today has no purpose, because popurp_0001 shipped without a
backfill, so the no-purpose path is the ordinary one.
"""
from app import db

OPENING = 'PAYMENT FOR THE PURCHASE OF '


def _append_unique(seq, value):
    """Order of first appearance, no repeats, blanks ignored."""
    value = (value or '').strip()
    if value and value not in seq:
        seq.append(value)


def _line_description(item, po_item=None):
    """What to call this line: its own text, else the product's name."""
    source = po_item if po_item is not None else item
    text = (getattr(source, 'description', None) or '').strip()
    if text:
        return text
    product = getattr(source, 'product', None) or getattr(item, 'product', None)
    return (getattr(product, 'name', None) or '').strip()


def _reference_line(po_numbers, received_month, invoice_number, rr_number=None):
    """One document's citation: '-PO#00984, SI#67051, RR#00634 - JULY 2026'.

    Segment ORDER is the legacy order, not append-at-the-end: the supplier
    invoice sits between the order and the receipt.

    THE `#` FORM, and the RR NUMBER, are the owner's current convention (2026-09-08,
    from APV 0001). The previous form -- 'PO NO.00742, SI NO.403159, RR - OCTOBER 2025'
    -- was measured across 1353 particulars in PhilGen's legacy register and was right
    for its time; vouchers written from here on follow the new one, and the old text
    stays untouched in the vouchers that already carry it.

    The receipt NUMBER is new information, not a reformatting: the previous line cited
    a receipt only by month, so which receipt was being billed could not be read off the
    voucher at all.
    """
    segments = []
    if po_numbers:
        segments.append('PO#' + ' & '.join(po_numbers))
    if invoice_number:
        segments.append('SI#' + invoice_number)
    # The receipt segment carries its number and its month together, so a voucher
    # citing several receipts keeps each number beside its own month.
    if rr_number and received_month:
        segments.append('RR#%s - %s' % (rr_number, received_month))
    elif rr_number:
        segments.append('RR#' + rr_number)
    elif received_month:
        # A receipt with no number is not reachable today (rr_number is NOT NULL), but
        # the month alone is still a true statement, so it is kept rather than dropped.
        segments.append('RR - ' + received_month)
    return '-' + ', '.join(segments) if segments else ''


def build_particulars(po_ids, rr_ids, invoice_number=None):
    """The Notes text for a voucher billing these purchase orders and receipts.

    `po_ids` are orders billed DIRECTLY (the services path); `rr_ids` are
    receipts (the goods path), each citing the orders behind its own lines.
    Unknown ids are skipped rather than raising -- they arrive from a hidden
    form field the browser owns, and a stale one must not 500 the page.
    """
    from app.purchase_orders.models import PurchaseOrder
    from app.receiving_reports.models import ReceivingReport

    invoice_number = (invoice_number or '').strip()
    items, purposes, references = [], [], []

    for po_id in (po_ids or []):
        po = db.session.get(PurchaseOrder, po_id)
        if po is None:
            continue
        for line in po.line_items:
            _append_unique(items, _line_description(line))
        _append_unique(purposes, po.purpose)
        references.append(([po.po_number] if po.po_number else [], None, None))

    for rr_id in (rr_ids or []):
        rr = db.session.get(ReceivingReport, rr_id)
        if rr is None:
            continue
        po_numbers = []
        for line in rr.line_items:
            po_item = line.purchase_order_item
            _append_unique(items, _line_description(line, po_item))
            order = getattr(po_item, 'order', None)
            if order is not None:
                _append_unique(purposes, order.purpose)
                if order.po_number:
                    _append_unique(po_numbers, order.po_number)
        month = rr.receipt_date.strftime('%B %Y').upper() if rr.receipt_date else None
        references.append((po_numbers, month, rr.rr_number))

    if not references and not items:
        return ''

    # The voucher carries ONE vendor_invoice_number, so it can only be attributed
    # when there is a single document to attribute it to. Legacy vouchers citing
    # several orders give each its OWN invoice number -- repeating the one we have
    # on every line would state something false about all but one of them.
    show_invoice = invoice_number if len(references) == 1 else ''

    lines = []
    if items:
        lines.append(OPENING + ', '.join(items))
    lines.extend(purposes)
    for po_numbers, month, rr_number in references:
        reference = _reference_line(po_numbers, month, show_invoice, rr_number)
        if reference:
            lines.append(reference)
    return '\n'.join(lines)
