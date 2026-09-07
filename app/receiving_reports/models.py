"""Receiving Report -- records goods received against an approved Purchase Order.
Buy-side mirror of DeliveryReceipt. Operational, NOT accounting: posts no journal entry in v1.

The RR is a control document -- it caps how much a Bill can charge (bill-what-you-received) and
records receipt. It is NOT a GRNI accrual today, but two seams keep that door open without a model
rebuild: `journal_entry_id` (a future accrual JE) and `accounts_payable_id` (the billing link,
Phase 3). Middle link of PO -> RR -> Bill.
"""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

# RR statuses that CONSUME the PO's open quantity (draft & cancelled do not).
# No 'delivered' step on the buy-side (that is a sell-side concept), so: approved + billed.
COMMITTED_STATUSES = ('approved', 'billed')


class ReceivingReport(RowVersioned, db.Model):
    __tablename__ = 'receiving_reports'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    rr_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    receipt_date = db.Column(db.Date, nullable=False, index=True)

    # The header vendor IS the key: one receipt covers one vendor, and the PO(s) it
    # draws on are derived per-line through `purchase_order_item` (see .purchase_orders).
    # There is deliberately NO header purchase_order_id -- one receipt may settle
    # several of a vendor's orders, so no single header FK can be true (dropped in
    # migration rrmulti_0001).
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=False, index=True)
    vendor_name = db.Column(db.String(200), nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)
    remarks = db.Column(db.Text)

    # Billing seam (Phase 3): set when a Bill is cut against this RR. Null until billed.
    accounts_payable_id = db.Column(db.Integer, db.ForeignKey('accounts_payable.id'),
                                    nullable=True, index=True)
    # Accrual seam (deferred): a future GRNI / period-end reversing JE attaches here. Inert in v1.
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    # draft -> submitted -> approved, mirroring the Purchase Requisition's and
    # Purchase Order's. Before this a receipt went draft -> approved directly and
    # approve is accountant-or-above, so the staff receiver who actually counted
    # the goods could record the receipt and then move it nowhere.
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500))
    # --- Printed signatories -------------------------------------------------
    # FREE TEXT, and deliberately NOT derived from created_by/submitted_by/
    # approved_by_id: the people who sign a receiving report are frequently NOT CAS users.
    # Deriving them once printed "System Administrator" three times on a single
    # requisition (see app/company_settings/views.py). `approved_by` therefore
    # sits alongside `approved_by_id` and means something different -- the same
    # pairing PurchaseOrder already carries.
    #
    # Per-DOCUMENT (owner directive, 2026-08-21), matching PurchaseOrder. They
    # were company-wide settings, so a one-off signatory became permanent for
    # every future printout. A new document still pre-fills from that company
    # setting, which is what keeps existing installs printing what they print
    # today; once saved the document prints its OWN values.
    #
    # Role labels are receiving report's own, not PurchaseOrder's -- they match the
    # defaults already used on the printout.
    prepared_by = db.Column(db.String(100))
    checked_by = db.Column(db.String(100))
    received_by = db.Column(db.String(100))

    line_items = db.relationship('ReceivingReportItem', backref='receiving_report',
                                 lazy='select', cascade='all, delete-orphan',
                                 order_by='ReceivingReportItem.line_number')

    def __repr__(self):
        return f'<ReceivingReport {self.rr_number} - {self.status}>'

    @property
    def purchase_orders(self):
        """Distinct POs this receipt draws on, ordered by number.

        Derived from the lines, never from a header column: one receipt may
        settle several of a vendor's orders, so no single header FK can be true.
        NOT every line has one: since rrdirect_0001 a line may be a DIRECT receipt
        (`purchase_order_item_id` NULL) for goods that arrived without an order. Such
        lines contribute no PO here, which is why the None guards below are load-bearing
        rather than defensive habit.
        """
        seen, out = set(), []
        for li in self.line_items:
            poi = li.purchase_order_item
            # PurchaseOrderItem's backref to its header is named 'order', not
            # 'purchase_order' -- see PurchaseOrder.line_items(backref='order').
            po = poi.order if poi else None
            if po is not None and po.id not in seen:
                seen.add(po.id)
                out.append(po)
        return sorted(out, key=lambda p: (p.po_number or ''))

    @property
    def po_number_display(self):
        """What a list column shows: the number when unambiguous, else a count."""
        pos = self.purchase_orders
        if not pos:
            return ''
        return pos[0].po_number if len(pos) == 1 else f'{len(pos)} POs'

    def to_dict(self):
        return {
            'id': self.id, 'rr_number': self.rr_number, 'status': self.status,
            'receipt_date': self.receipt_date.isoformat() if self.receipt_date else None,
            'purchase_order_number': self.po_number_display or None,
            'vendor_name': self.vendor_name,
        }


class ReceivingReportItem(db.Model):
    __tablename__ = 'receiving_report_items'

    id = db.Column(db.Integer, primary_key=True)
    receiving_report_id = db.Column(db.Integer, db.ForeignKey('receiving_reports.id'),
                                    nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    # NULLABLE since rrdirect_0001: a line with no order line is a DIRECT receipt --
    # goods that arrived without a purchase order. Such a line takes its unit,
    # description and cost from `product_id` below instead.
    purchase_order_item_id = db.Column(db.Integer, db.ForeignKey('purchase_order_items.id'),
                                       nullable=True, index=True)
    purchase_order_item = db.relationship('PurchaseOrderItem',
                                          foreign_keys=[purchase_order_item_id])
    # A snapshot for print on a PO-backed line; on a DIRECT line it is the line's only
    # identity -- what was received, what unit it is in, and what it is valued at all
    # come from it.
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    # The unit a DIRECT receipt arrived in (rruom_0001). NULL on a PO-backed line, which
    # takes its unit from the order line, and NULL on a direct line the receiver did not
    # override -- that one falls back to the product's default. The FK lives here and
    # NOT in the migration: a SQLite batch add_column cannot carry an inline ForeignKey.
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'),
                                   nullable=True)
    unit_of_measure_ref = db.relationship('UnitOfMeasure',
                                          foreign_keys=[unit_of_measure_id])
    product = db.relationship('Product', foreign_keys=[product_id])
    received_quantity = db.Column(db.Numeric(15, 4), nullable=False)

    # R-03 slice 2a-ii: points at the StockMovement this line's receipt posted
    # (tracked products only -- NULL for an untracked line or a not-yet-approved RR).
    stock_movement_id = db.Column(db.Integer, db.ForeignKey('stock_movements.id'), nullable=True)
    stock_movement = db.relationship('StockMovement')

    # A RR line's quantity is the RECEIVED quantity; UoM/price belong to the PO line it receives.
    @property
    def quantity(self):
        return self.received_quantity

    # A DIRECT receipt (no order line) takes its unit, description and cost from the
    # PRODUCT MASTER. That is the whole shape of the feature: a receiving report records
    # what arrived, never what it is worth, so nothing here may come from the receiver
    # (owner, 2026-09-06: "RR cannot have unit price").

    @property
    def unit_of_measure(self):
        """The unit this line is counted in, most specific source first.

        An order line settles it when there is one -- that is what the vendor was asked
        for. Otherwise the receiver's own choice wins over the product's default, because
        goods can arrive by the box for a product carried by the piece, and the person
        unpacking them is the one who knows.
        """
        poi = self.purchase_order_item
        if poi:
            return poi.unit_of_measure
        if self.unit_of_measure_ref:
            return self.unit_of_measure_ref
        return self.product.default_unit_of_measure if self.product else None

    @property
    def uom_text(self):
        poi = self.purchase_order_item
        if poi:
            return poi.uom_text
        # A direct line has no free-text unit of its own; the product's default unit
        # carries a code, which unit_of_measure above already returns.
        return None

    @property
    def description(self):
        """What was received. The order line's wording when there is one -- it is what
        the vendor was actually asked for -- else the product's own name."""
        poi = self.purchase_order_item
        if poi and poi.description:
            return poi.description
        return self.product.name if self.product else None

    @property
    def is_direct(self):
        """True when this line records goods that arrived WITHOUT a purchase order."""
        return self.purchase_order_item_id is None

    @property
    def po_number(self):
        """The PO number this line receives against, derived through the line's
        own `purchase_order_item` -- never through a header FK. One receipt can
        settle several of a vendor's orders, so each line carries its own PO.

        `PurchaseOrderItem`'s backref to its header is named `order`, not
        `purchase_order` -- see PurchaseOrder.line_items(backref='order'). Returns
        '' (never raises) when the line item or its order is missing, so both
        print templates can render it unguarded."""
        poi = self.purchase_order_item
        po = poi.order if poi else None
        return po.po_number if po else ''

    def to_dict(self):
        poi = self.purchase_order_item
        return {
            'id': self.id, 'line_number': self.line_number,
            'purchase_order_item_id': self.purchase_order_item_id,
            'received_quantity': float(self.received_quantity) if self.received_quantity is not None else 0.0,
            'ordered_quantity': float(poi.quantity) if (poi and poi.quantity is not None) else None,
            'description': self.description,
            'is_direct': self.is_direct,
            'product_code': (poi.product.code if (poi and poi.product) else (self.product.code if self.product else None)),
            'product_name': (poi.product.name if (poi and poi.product) else (self.product.name if self.product else None)),
            'uom': (self.unit_of_measure.code if self.unit_of_measure
                    else (poi.uom_text if poi else None)),
            'unit_price': float(poi.unit_price) if (poi and poi.unit_price is not None) else None,
        }


def po_line_open_qty(po_item, exclude_rr_id=None):
    """Ordered qty of a PO line minus the qty already received by non-cancelled, non-draft RR
    lines (statuses in COMMITTED_STATUSES). Pass exclude_rr_id to leave a specific RR out of the
    sum (used when re-checking the RR being approved)."""
    ordered = Decimal(str(po_item.quantity or 0))
    q = (db.session.query(db.func.coalesce(db.func.sum(ReceivingReportItem.received_quantity), 0))
         .join(ReceivingReport, ReceivingReportItem.receiving_report_id == ReceivingReport.id)
         .filter(ReceivingReportItem.purchase_order_item_id == po_item.id)
         .filter(ReceivingReport.status.in_(COMMITTED_STATUSES)))
    if exclude_rr_id is not None:
        q = q.filter(ReceivingReport.id != exclude_rr_id)
    received = Decimal(str(q.scalar() or 0))
    return ordered - received


def generate_rr_number(branch_id=None):
    """Plain continuous 5-digit sequence: 00001, 00002, ... No prefix, no reset.

    Mirrors generate_invoice_number's contract exactly (global, not per-branch;
    branch_id accepted for call-site symmetry). Each RR gets the next number after
    the highest existing purely-numeric rr_number -- this deliberately includes
    legacy-migrated literal numbers, not just CAS-generated ones. Legacy prefixed
    numbers (e.g. the old 'RR-2026-07-0030' format) are ignored.
    """
    from app.utils.doc_numbering import next_document_number
    return next_document_number(ReceivingReport, ReceivingReport.rr_number, branch_id)


#: The printed signatory columns, in print order. RR's own roles -- NOT the
#: Purchase Order's: a receipt is checked and received, not approved.
SIGNATORY_FIELDS = ('prepared_by', 'checked_by', 'received_by')

#: Role labels, matching company_settings' RR defaults exactly so the printout
#: wording does not change when the value moves onto the document.
SIGNATORY_ROLES = ('Prepared by', 'Checked by', 'Received by')
