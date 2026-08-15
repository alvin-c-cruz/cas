"""Purchase Order — a committed order to a vendor. Buy-side mirror of SalesOrder.
Operational, NOT accounting: posts no journal entry, has no GL account/WHT/payment.
The Bill (Accounts Payable) is the first document in the chain that hits the ledger.

vat_treatment mirrors Quotation (inclusive / exclusive / zero_rated). Two seams are created
here but stay inert until later phases: `purchase_request_id` (Phase 4 PR->PO conversion) and
`accounts_payable_id` (Phase 3 billing). Line-level `received_quantity` / `billed_quantity` are
written by the Receiving Report (Phase 2) and the AP picker (Phase 3) respectively."""
from decimal import Decimal, ROUND_HALF_UP
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned
from app.amendments.mixins import Amendable
from app.amendments.snapshot import money

VAT_TREATMENTS = ('inclusive', 'exclusive', 'zero_rated')
STANDARD_VAT_RATE = Decimal('12')


class PurchaseOrder(Amendable, RowVersioned, db.Model):
    __tablename__ = 'purchase_orders'

    DOCUMENT_TYPE = 'purchase_orders'

    SNAPSHOT_HEADER_FIELDS = (
        'po_number', 'order_date', 'expected_date', 'vendor_id', 'vendor_name',
        'vendor_tin', 'vendor_address', 'payment_terms', 'reference', 'notes',
        'vat_treatment', 'status', 'subtotal', 'vat_amount', 'vat_override',
        'total_amount', 'purchase_request_id',
        # accounts_payable_id IS live state -- purchase_billing.py sets it when the
        # PO is billed and clears it on void. Unlike received_quantity/billed_quantity
        # (never written, excluded below), omitting it would lose whether this PO was
        # billed and onto which bill.
        'accounts_payable_id',
        'branch_id',
        # Provenance: Rev 0 is "the PO as originally approved" -- losing who
        # approved it and when makes that snapshot incomplete.
        'approved_by_id', 'approved_at', 'cancelled_by_id', 'cancelled_at',
        'cancel_reason',
    )

    # received_quantity/billed_quantity are deliberately EXCLUDED: nothing in the
    # app writes them, so snapshotting their permanent 0 would record a false fact.
    SNAPSHOT_LINE_FIELDS = (
        'line_number', 'product_id', 'description', 'quantity', 'unit_price',
        'amount', 'uom_text', 'unit_of_measure_id', 'vat_category', 'vat_rate',
        'line_total', 'vat_amount',
    )

    SNAPSHOT_MONEY_FIELDS = ('subtotal', 'vat_amount', 'total_amount')

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    po_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    order_date = db.Column(db.Date, nullable=True, index=True)
    expected_date = db.Column(db.Date, nullable=True)

    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True, index=True)
    vendor = db.relationship('Vendor')
    vendor_name = db.Column(db.String(200))
    vendor_tin = db.Column(db.String(30))
    vendor_address = db.Column(db.String(300))

    payment_terms = db.Column(db.String(50), default='Net 30')
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text, nullable=False, default='')
    vat_treatment = db.Column(db.String(10), default='inclusive', nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    # Chain link: the Purchase Request this PO was created from on convert (null for directly-entered
    # POs). Plain Integer (no ORM FK) on purpose -- the reverse edge PurchaseRequest.purchase_order_id
    # forms the pair; declaring an FK both ways creates a metadata cycle SQLAlchemy can't sort for
    # create_all/drop_all. Mirrors SalesOrder.quotation_id (migration 29500ade76f8). Inert until Phase 4.
    purchase_request_id = db.Column(db.Integer, nullable=True, index=True)

    # Billing seam (Phase 3): set when a Bill is cut against this PO (services path). Null until billed.
    accounts_payable_id = db.Column(db.Integer, db.ForeignKey('accounts_payable.id'), nullable=True)

    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_override = db.Column(db.Boolean, default=False, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500), nullable=True)

    line_items = db.relationship('PurchaseOrderItem', backref='order', lazy='select',
                                 cascade='all, delete-orphan',
                                 order_by='PurchaseOrderItem.line_number')

    #: Statuses from which an amendment is allowed. 'partially_received' is in
    #: VALID_PO_STATUSES but is never assigned by any code path today (see the
    #: spec's Out of scope); accepting it costs nothing and is correct when that
    #: transition ships. 'closed' is deliberately absent: billing sets it
    #: (purchase_billing.py), so a billed PO is unreachable here by design.
    AMEND_STATUSES = ('approved', 'partially_received')

    child_document_label = 'Receiving Report'

    def consumed_qty(self, line):
        """Quantity already committed by non-draft, non-cancelled Receiving Reports."""
        from app.receiving_reports.models import po_line_open_qty
        return Decimal(str(line.quantity or 0)) - po_line_open_qty(line)

    def has_any_child_reference(self, line):
        """True if ANY Receiving Report line references this PO line, whatever its status.

        Deliberately STATUS-AGNOSTIC and wider than consumed_qty. A draft or
        cancelled RR contributes zero received quantity and so would not, on its
        own, block removing this line -- but SQLite FK enforcement is off app-wide,
        so deleting the line anyway leaves that RR line's purchase_order_item_id
        dangling, and the next po_line_open_qty() on it dereferences None and 500s,
        unrecoverable through the UI.
        """
        from app.receiving_reports.models import ReceivingReportItem
        return (db.session.query(ReceivingReportItem.id)
                .filter(ReceivingReportItem.purchase_order_item_id == line.id)
                .first() is not None)

    def has_approvable_line(self):
        """True when at least one line carries BOTH a unit price and an amount.

        approve()'s precondition -- and, since an amendment rewrites an already
        approved order, its postcondition too. Amend must not be able to leave a
        Purchase Order in a shape approve() would have refused: deleting every row
        in the amend form posts an explicit `[]`, which validate_amendment allows
        when nothing has been received (removing an untouched line is legal), and
        that left an APPROVED order with zero lines and a 0.00 total -- still
        listed by billable_pos_for(), still printable, reported to the user as a
        success.

        ONE predicate, called by both routes, on purpose. The same rule typed out
        twice is precisely how that hole survived a review: the absent-`line_items`
        door was closed by hand and the explicit-`[]` door beside it was not.
        """
        return any((li.unit_price or 0) > 0 and (li.amount or 0) > 0
                   for li in self.line_items)

    def calculate_totals(self):
        """Header totals branch on vat_treatment (mirror Quotation.calculate_totals)."""
        gross = sum((Decimal(str(li.amount or 0)) for li in self.line_items), Decimal('0.00'))
        if self.vat_treatment == 'exclusive':
            self.subtotal = gross                                 # net
            self.vat_amount = (gross * STANDARD_VAT_RATE / 100).quantize(Decimal('0.01'), ROUND_HALF_UP)
            self.total_amount = self.subtotal + self.vat_amount
        elif self.vat_treatment == 'zero_rated':
            self.subtotal = gross
            self.vat_amount = Decimal('0.00')
            self.total_amount = gross
        else:  # inclusive
            self.subtotal = gross
            self.vat_amount = sum((Decimal(str(li.vat_amount or 0)) for li in self.line_items),
                                  Decimal('0.00'))
            self.total_amount = gross

    def snapshot_line_extras(self, line):
        return {
            'product_code': line.product.code if line.product else None,
            'product_name': line.product.name if line.product else None,
            'uom_code': (line.unit_of_measure.code if line.unit_of_measure
                         else line.uom_text),
            'unit_price_display': money(line.unit_price),
            'amount_display': money(line.amount),
        }

    def snapshot_header_extras(self):
        return {'branch_name': self.branch.name if self.branch else None}

    def to_dict(self):
        return {'id': self.id, 'po_number': self.po_number,
                'order_date': self.order_date.isoformat() if self.order_date else None,
                'vendor_name': self.vendor_name, 'status': self.status,
                'vat_treatment': self.vat_treatment,
                'total_amount': float(self.total_amount) if self.total_amount is not None else 0.0}


class PurchaseOrderItem(db.Model):
    __tablename__ = 'purchase_order_items'

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'),
                                  nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255), nullable=True)   # free-text (service lines w/o a product)
    amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    quantity = db.Column(db.Numeric(15, 4), nullable=True)
    unit_price = db.Column(db.Numeric(15, 2), nullable=True)
    uom_text = db.Column(db.String(20), nullable=True)
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    unit_of_measure = db.relationship('UnitOfMeasure')
    product = db.relationship('Product')
    vat_category = db.Column(db.String(100))
    vat_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)
    line_total = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Fulfilment tracking: received_quantity written by the Receiving Report (Phase 2),
    # billed_quantity written by the AP billing picker (Phase 3). Both default 0.
    received_quantity = db.Column(db.Numeric(15, 4), default=0)
    billed_quantity = db.Column(db.Numeric(15, 4), default=0)

    #: The requisition line this PO line was pulled from, if any. Bare Integer,
    #: not a ForeignKey: SQLite batch add_column cannot emit an unnamed FK
    #: ("Constraint must have a name") and FK enforcement is off app-wide.
    #: Same treatment as SalesOrder.quotation_id (migration 29500ade76f8).
    #: NULL means the line was typed by hand, which is true of every line that
    #: existed before this feature.
    source_pr_item_id = db.Column(db.Integer, nullable=True, index=True)

    def calculate_amounts(self):
        """Extract VAT from VAT-inclusive amount. Mirrors SalesOrderItem/QuotationItem."""
        if self.quantity is not None and self.unit_price is not None:
            q = Decimal(str(self.quantity)); up = Decimal(str(self.unit_price))
            if q > 0 and up > 0:
                self.amount = (q * up).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amt = Decimal(str(self.amount or 0))
        rate = Decimal(str(self.vat_rate or 0))
        if rate > 0:
            net = (amt / (1 + rate / 100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.vat_amount = amt - net
        else:
            self.vat_amount = Decimal('0.00')
        self.line_total = amt

    def to_dict(self):
        return {
            'id': self.id, 'line_number': self.line_number,
            'description': self.description,
            'amount': float(self.amount) if self.amount is not None else 0.0,
            'quantity': float(self.quantity) if self.quantity is not None else None,
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'uom_text': self.uom_text, 'unit_of_measure_id': self.unit_of_measure_id,
            'uom_display': (self.unit_of_measure.code if self.unit_of_measure else self.uom_text),
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else None,
            'product_name': self.product.name if self.product else None,
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate) if self.vat_rate is not None else 0.0,
            'received_quantity': float(self.received_quantity) if self.received_quantity is not None else 0.0,
            'billed_quantity': float(self.billed_quantity) if self.billed_quantity is not None else 0.0,
            # Feeds the form's EXISTING payload on a draft edit / amendment.
            # Omitting it does not error -- addRow simply never sets the dataset
            # key, the serialiser posts null, and every pulled line is silently
            # orphaned on the next save, reopening a requisition that is in fact
            # still on order.
            'source_pr_item_id': self.source_pr_item_id,
        }


def generate_po_number():
    """Plain continuous 5-digit sequence: 00001, 00002, ... No prefix, no reset.

    Mirrors generate_invoice_number's contract exactly. Each PO gets the next
    number after the highest existing purely-numeric po_number -- this
    deliberately includes legacy-migrated literal numbers, not just CAS-generated
    ones. Legacy prefixed numbers (e.g. the old 'PO-2026-07-0030' format) are
    ignored.
    """
    rows = PurchaseOrder.query.with_entities(PurchaseOrder.po_number).all()
    nums = [int(r[0]) for r in rows if r[0] and r[0].isdigit()]
    next_num = (max(nums) + 1) if nums else 1
    return f'{next_num:05d}'
