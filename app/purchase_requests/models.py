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
        'pr_number', 'request_date', 'date_needed', 'reason', 'status', 'branch_id',
        # purchase_order_id IS live state -- convert() writes it (views.py:371)
        # and it is the only record of what this requisition became. Omitting it
        # was slice 1's first defect, in its PO equivalent (accounts_payable_id):
        # the snapshot then cannot say whether the document was ever consumed.
        'purchase_order_id',
        # Provenance: Rev 0 is "the PR as originally approved", so losing who
        # moved it through each state makes that snapshot incomplete. PR has a
        # longer state history than PO -- submitted and rejected as well.
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

    #: Only 'approved'. 'submitted' is past draft but PRE-approval, and the
    #: spec's trigger is approval. 'converted' is excluded because conversion
    #: has already produced a draft PO the buyer is pricing -- see is_converted.
    AMEND_STATUSES = ('approved',)

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

    line_items = db.relationship('PurchaseRequestItem', backref='purchase_request',
                                 lazy='select', cascade='all, delete-orphan',
                                 order_by='PurchaseRequestItem.line_number')

    def is_converted(self):
        """True once this requisition has produced a Purchase Order.

        PR's whole "already consumed" question, and it is HEADER-level -- unlike
        PO and SO, where consumption is per line. `convert()` sets `status` and
        `purchase_order_id` together (views.py:370-371), so either alone would
        normally do; reading BOTH means a single failed commit that left one of
        them behind cannot make an already-converted requisition amendable again.

        Amending a converted PR would change nothing downstream: conversion
        COPIES the lines into a draft PO rather than pointing at them, so the
        buyer keeps pricing the old numbers while the requisition claims new
        ones. That is the lie this guard exists to prevent.
        """
        return self.status == 'converted' or self.purchase_order_id is not None

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
    # PR is the first adopter with NO CHILDREN. Nothing in the app declares a
    # purchase_request_item_id; the only downstream edge is the header-level
    # purchase_order_id. Both hooks are therefore constant, and deliberately so:
    # they are what let the shared validator run against PR unchanged, which is
    # the answer slices 4-5 need before AP/CD/RR/DR adopt it.

    child_document_label = 'Purchase Order'

    def consumed_qty(self, line):
        """Always zero -- nothing can consume part of a requisition line."""
        return Decimal('0')

    def has_any_child_reference(self, line):
        """Always False -- no table carries a purchase_request_item_id.

        Contrast PO, where this is status-agnostic and strictly wider than the
        quantity floor because deleting a referenced line strands a
        ReceivingReportItem FK with SQLite FK enforcement off. PR has no such
        child, so a line may always be removed on this axis.
        """
        return False

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


def generate_pr_number(branch_id=None):
    """Plain continuous 5-digit sequence: 00001, 00002, ... No prefix, no reset.

    Mirrors generate_invoice_number's contract exactly (global, not per-branch;
    branch_id accepted for call-site symmetry). Each PR gets the next number after
    the highest existing purely-numeric pr_number -- this deliberately includes
    legacy-migrated literal numbers, not just CAS-generated ones. Legacy prefixed
    numbers (e.g. the old 'PR-2026-07-0030' format) are ignored.
    """
    rows = PurchaseRequest.query.with_entities(PurchaseRequest.pr_number).all()
    nums = [int(r[0]) for r in rows if r[0] and r[0].isdigit()]
    next_num = (max(nums) + 1) if nums else 1
    return f'{next_num:05d}'
