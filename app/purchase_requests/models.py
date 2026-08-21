"""Purchase Request -- a thin internal requisition. Front of the buy-side chain
(PR -> PO -> RR -> Bill). Mirror of Quotation on the sell side. Operational, NOT accounting:
posts no journal entry.

A requisition records WHAT is needed (product / UoM / qty / description) and WHY (reason) --
NO vendor and NO price. On approval it converts into a *draft* Purchase Order where the buyer
adds the vendor and prices (mirror of quotations.accept -> draft SO)."""
from decimal import Decimal

from app import db
from app.amendments.mixins import Amendable
from app.utils import ph_now
from app.utils.concurrency import RowVersioned


class PurchaseRequest(Amendable, RowVersioned, db.Model):
    __tablename__ = 'purchase_requests'

    DOCUMENT_TYPE = 'purchase_requests'

    SNAPSHOT_HEADER_FIELDS = (
        # date_needed belongs here for the same reason request_date does: an
        # amendment that moves the date the goods are wanted by is a real change
        # to the document, and a revision that omits it cannot say what altered.
        'pr_number', 'request_date', 'date_needed', 'date_needed_asap', 'reason',
        'status', 'branch_id',
        # purchase_order_id IS live state -- convert() writes it (views.py:371)
        # and it is the only record of what this requisition became. Omitting it
        # was slice 1's first defect, in its PO equivalent (accounts_payable_id):
        # the snapshot then cannot say whether the document was ever consumed.
        'purchase_order_id',
        # Provenance: Rev 0 is "the PR as originally approved", so losing who
        # moved it through each state makes that snapshot incomplete. PR has a
        # longer state history than PO -- submitted and rejected as well.
        'prepared_by', 'noted_by', 'approved_by',
        'submitted_by_id', 'submitted_at',
        'approved_by_id', 'approved_at',
        'rejected_by_id', 'rejected_at', 'reject_reason',
        'cancelled_by_id', 'cancelled_at', 'cancel_reason',
    )

    SNAPSHOT_LINE_FIELDS = (
        'line_number', 'product_id', 'description', 'quantity',
        'uom_text', 'unit_of_measure_id',
    )

    #: EMPTY on purpose. PurchaseRequestItem has no unit_price, amount or VAT
    #: column -- a requisition records WHAT is needed, and the buyer supplies
    #: pricing at PO conversion. Declaring a money field here would emit a
    #: *_display key for a value that does not exist.
    SNAPSHOT_MONEY_FIELDS = ()

    #: PR lines may legitimately carry no quantity: the column is nullable and
    #: _parse_and_attach_pr_lines keeps a line that names a product OR a
    #: description. Without this the shared validator refused every such line as
    #: "could not read the submitted quantity" -- a requisition recording
    #: "Cement, quantity to follow" could not be amended at all, not even
    #: re-saved unchanged.
    LINE_QUANTITY_REQUIRED = False

    #: 'partially_converted' is amendable because the shared validator now has
    #: real consumed_qty/has_any_child_reference hooks -- it refuses to shrink
    #: or delete an already-ordered line while permitting untouched ones.
    #: 'converted' stays out: every line is consumed, so the only edit the
    #: validator would allow is ADDING demand to a fully ordered requisition,
    #: which belongs on a new requisition. Carry-over of current behaviour.
    AMEND_STATUSES = ('approved', 'partially_converted')

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    pr_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    request_date = db.Column(db.Date, nullable=False, index=True)
    #: When the goods are wanted BY -- distinct from request_date, which is when
    #: the requisition was raised. Nullable and unvalidated by owner directive
    #: (2026-08-14): it matches the paper form, and mirrors
    #: PurchaseOrder.expected_date, which is also optional and unchecked.
    #: Nullable is not a preference -- requisitions already exist that have none.
    date_needed = db.Column(db.Date, nullable=True)
    #: ASAP -- wanted immediately, no specific date. MUTUALLY EXCLUSIVE with
    #: date_needed: setting this clears that, so one row can never carry two
    #: answers to the same question (a printout reading ASAP while a report
    #: sorts the row by a stale date). Enforced in the views, not by a DB
    #: constraint, because SQLite CHECK constraints here would need a table
    #: rebuild on every future column add.
    date_needed_asap = db.Column(db.Boolean, nullable=False, default=False,
                                 server_default='0')
    reason = db.Column(db.Text)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    # Forward-link to the PO created on convert (this IS a real ORM FK, mirroring
    # Quotation.sales_order_id). The reverse edge PurchaseOrder.purchase_request_id is a bare
    # Integer, so only this side declares the FK -- no metadata cycle.
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'),
                                  nullable=True, index=True)
    purchase_order = db.relationship('PurchaseOrder', foreign_keys=[purchase_order_id])

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    reject_reason = db.Column(db.String(500))
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500))
    # --- Printed signatories -------------------------------------------------
    # FREE TEXT, and deliberately NOT derived from created_by/submitted_by/
    # approved_by_id: the people who sign a requisition are frequently NOT CAS users.
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
    # Role labels are requisition's own, not PurchaseOrder's -- they match the
    # defaults already used on the printout.
    prepared_by = db.Column(db.String(100))
    noted_by = db.Column(db.String(100))
    approved_by = db.Column(db.String(100))

    line_items = db.relationship('PurchaseRequestItem', backref='purchase_request',
                                 lazy='select', cascade='all, delete-orphan',
                                 order_by='PurchaseRequestItem.line_number')

    def is_converted(self):
        """True once every line has been fully ordered.

        Was `status == 'converted' or purchase_order_id is not None`. That
        breaks under partial allocation: the whole-requisition shortcut sets
        purchase_order_id even when it pulls only part of the requisition, so
        the old form would call a half-ordered requisition converted and freeze
        it against amendment.
        """
        from app.purchase_requests.allocation import pr_line_is_open
        if self.status == 'converted':
            return True
        if not self.line_items:
            return False
        return not any(pr_line_is_open(li) for li in self.line_items)

    def has_requested_line(self):
        """True when at least one line names a product OR a description.

        PR's own rule, already enforced on the way IN by
        `_parse_and_attach_pr_lines` ('Line N: enter a product or a description.'
        / 'Add at least one requested item.'). Restating it as a method makes it
        assertable as a POSTcondition, so an amendment can be judged on its
        APPLIED RESULT rather than by re-deriving the rule from the payload --
        re-deriving is exactly how the equivalent hole survived its first fix on
        the Purchase Order side.

        Note this is PR's rule, not PO's `has_approvable_line` (unit price AND
        amount) nor SO's `has_usable_line` (product AND amount > 0). A
        requisition legitimately carries neither price nor amount.
        """
        for line in self.line_items:
            if line.product_id is not None:
                return True
            if (line.description or '').strip():
                return True
        return False

    # -- the shared validator's document hooks --------------------------------
    # PR now HAS a per-line child: PurchaseOrderItem.source_pr_item_id. Both
    # hooks were previously constants above a comment saying no table carries a
    # purchase_request_item_id; one does now, so both derive from it.

    child_document_label = 'Purchase Order'

    def consumed_qty(self, line):
        """How much of this requisition line is already on a purchase order.

        Was hardcoded to zero, above a comment saying nothing can consume part
        of a requisition. PurchaseOrderItem.source_pr_item_id now can, so the
        shared amendment validator refuses to shrink a line below what has been
        ordered against it.
        """
        from app.purchase_requests.allocation import pr_line_ordered_qty
        return pr_line_ordered_qty(line)

    def has_any_child_reference(self, line):
        """Whether any committed purchase-order line points at this line.

        Strictly wider than the quantity floor, and that matters for an
        unquantified requisition line: it has no quantity to compare, so this
        is the only thing standing between it and deletion after it has been
        ordered.
        """
        from app.purchase_requests.allocation import _has_committed_reference
        return _has_committed_reference(line)

    def snapshot_line_extras(self, line):
        return {
            'product_code': line.product.code if line.product else None,
            'product_name': line.product.name if line.product else None,
            'uom_code': (line.unit_of_measure.code if line.unit_of_measure
                         else line.uom_text),
        }

    def snapshot_header_extras(self):
        return {
            'branch_name': self.branch.name if self.branch else None,
            'purchase_order_number': (self.purchase_order.po_number
                                      if self.purchase_order else None),
        }

    def to_dict(self):
        return {'id': self.id, 'pr_number': self.pr_number, 'status': self.status,
                'request_date': self.request_date.isoformat() if self.request_date else None,
                'date_needed': self.date_needed.isoformat() if self.date_needed else None,
                'date_needed_asap': bool(self.date_needed_asap),
                'purchase_order_id': self.purchase_order_id,
                'purchase_order_number': self.purchase_order.po_number if self.purchase_order else None}


class PurchaseRequestItem(db.Model):
    __tablename__ = 'purchase_request_items'

    id = db.Column(db.Integer, primary_key=True)
    purchase_request_id = db.Column(db.Integer, db.ForeignKey('purchase_requests.id'),
                                    nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    quantity = db.Column(db.Numeric(15, 4), nullable=True)
    uom_text = db.Column(db.String(20), nullable=True)
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    unit_of_measure = db.relationship('UnitOfMeasure')
    product = db.relationship('Product')
    # NO price / amount / vat -- the buyer supplies pricing at PO conversion.

    def to_dict(self):
        return {
            'id': self.id, 'line_number': self.line_number,
            'description': self.description,
            'quantity': float(self.quantity) if self.quantity is not None else None,
            'uom_text': self.uom_text, 'unit_of_measure_id': self.unit_of_measure_id,
            'uom_display': (self.unit_of_measure.code if self.unit_of_measure else self.uom_text),
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else None,
            'product_name': self.product.name if self.product else None,
        }


#: The printed signatory columns, in print order. Named per THIS document.
SIGNATORY_FIELDS = ('prepared_by', 'noted_by', 'approved_by')

#: Role label for each, matching company_settings' PR defaults exactly so the
#: printout wording does not change when the value moves onto the document.
SIGNATORY_ROLES = ('Prepared by', 'Noted by', 'Approved by')


def generate_pr_number(branch_id=None):
    """Plain continuous 5-digit sequence: 00001, 00002, ... No prefix, no reset.

    Mirrors generate_invoice_number's contract exactly (global, not per-branch;
    branch_id accepted for call-site symmetry). Each PR gets the next number after
    the highest existing purely-numeric pr_number -- this deliberately includes
    legacy-migrated literal numbers, not just CAS-generated ones. Legacy prefixed
    numbers (e.g. the old 'PR-2026-07-0030' format) are ignored.
    """
    from app.utils.doc_numbering import next_document_number
    return next_document_number(PurchaseRequest, PurchaseRequest.pr_number, branch_id)
