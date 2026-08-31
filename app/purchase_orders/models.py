"""Purchase Order — a committed order to a vendor. Buy-side mirror of SalesOrder.
Operational, NOT accounting: posts no journal entry, has no GL account/WHT/payment.
The Bill (Accounts Payable) is the first document in the chain that hits the ledger.

vat_treatment mirrors Quotation (inclusive / exclusive / zero_rated). Two seams are created
here but stay inert until later phases: `purchase_request_id` (Phase 4 PR->PO conversion) and
`accounts_payable_id` (Phase 3 billing). Line-level `received_quantity` / `billed_quantity` are
written by the Receiving Report (Phase 2) and the AP picker (Phase 3) respectively."""
import re
from decimal import Decimal, ROUND_HALF_UP
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned
from app.amendments.mixins import Amendable
from app.amendments.snapshot import money

VAT_TREATMENTS = ('inclusive', 'exclusive', 'zero_rated')

# The wording PurchaseOrderForm's SelectField shows (app/purchase_orders/forms.py:25).
# Form, detail and print must share the document's jargon, so the labels live in ONE
# place rather than being re-spelled per template.
VAT_TREATMENT_LABELS = {
    'inclusive': 'VAT Inclusive',
    'exclusive': 'VAT Exclusive',
    'zero_rated': 'Zero-Rated',
}

STANDARD_VAT_RATE = Decimal('12')


class PurchaseOrder(Amendable, RowVersioned, db.Model):
    __tablename__ = 'purchase_orders'

    DOCUMENT_TYPE = 'purchase_orders'

    SNAPSHOT_HEADER_FIELDS = (
        'po_number', 'order_date', 'expected_date', 'vendor_id', 'vendor_name',
        'vendor_tin', 'vendor_address', 'payment_terms', 'reference', 'purpose', 'notes',
        # Header state an amendment must preserve: Rev 0 has to record WHO the
        # order was routed past when it was originally approved.
        'prepared_by', 'checked_by', 'approved_by',
        'submitted_by_id', 'submitted_at',
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
    # What the order is FOR ("FOR PRODUCTION USE"). Header-level, printed once
    # above the lines -- PhilGen's legacy system stored the same string on every
    # line and grouped the print by it, but across 168 real POs (118 multi-line)
    # not one carries a second distinct value, so it is a header attribute.
    purpose = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=False, default='')

    # Signatories are PER PURCHASE ORDER, not company-wide -- deliberately unlike
    # the Purchase Requisition's and Receiving Report's, which are AppSettings
    # rows because the same three people sign every one of those.
    #
    # This client runs two purchasers, each holding her own pre-printed PO pad
    # (see next_po_number_for), and each routes her orders past different people.
    # A new PO therefore pre-fills from that PURCHASER's own last PO rather than
    # from a single company setting -- and stays editable, so a one-off signatory
    # does not become permanent.
    #
    # Names match the legacy Philgen form's fields verbatim, and the vocabulary
    # AP/CD/JE already use in their pre-printed layouts.
    prepared_by = db.Column(db.String(100))
    checked_by = db.Column(db.String(100))
    approved_by = db.Column(db.String(100))
    vat_treatment = db.Column(db.String(10), default='inclusive', nullable=False)

    # Legacy-pad parity (owner directive 2026-08-31, from the annotation on PO 00984:
    # "PO can be of any currency. default is PHP"). A LABEL ONLY -- printed beside the
    # total exactly as the pre-printed pad does. Nothing converts: the amount is still
    # booked in pesos, the RR values stock in pesos, the AP bill and the GL post in
    # pesos, and no FX rate exists anywhere in CAS. This is the first currency field in
    # the app; every other `currency` match in the tree is the word `concurrency`.
    # server_default as well as default, so the orders already on the five client
    # instances read 'PHP' after the migration instead of NULL -- a NULL would print an
    # empty label where the pad prints a currency.
    currency = db.Column(db.String(3), default='PHP', server_default='PHP', nullable=False)

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
    # draft -> submitted -> approved, mirroring the Purchase Requisition's. Before
    # this, a PO went draft -> approved directly and `approve` was accountant-only,
    # so a staff purchaser could build an order and then move it nowhere.
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_at = db.Column(db.DateTime)
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

    @property
    def vat_treatment_label(self):
        """Human wording for the stored token. Falls back to the raw value so an
        unrecognised token is visible on the page rather than printing blank."""
        return VAT_TREATMENT_LABELS.get(self.vat_treatment, self.vat_treatment)

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


def generate_po_number(branch_id=None):
    """Plain continuous 5-digit sequence: 00001, 00002, ... No prefix, no reset.

    Mirrors generate_invoice_number's contract exactly. Each PO gets the next
    number after the highest existing purely-numeric po_number -- this
    deliberately includes legacy-migrated literal numbers, not just CAS-generated
    ones. Legacy prefixed numbers (e.g. the old 'PO-2026-07-0030' format) are
    ignored.
    """
    from app.utils.doc_numbering import next_document_number
    return next_document_number(PurchaseOrder, PurchaseOrder.po_number, branch_id)


# Leading digits + an OPTIONAL trailing non-digit marker: '00001E', '00001',
# '30500'. A legacy prefixed number ('PO-2026-07-0030') does not match and is
# ignored, exactly as generate_po_number() ignores it.
_PO_NUMBER_RE = re.compile(r'^(\d+)(\D*)$')


SIGNATORY_FIELDS = ('prepared_by', 'checked_by', 'approved_by')


def group_lines_by_description(line_items):
    """[(description, [items], subtotal), ...] for the printed Purchase Order.

    Owner directive 2026-08-21: the printout groups its lines by the free-text
    Description rather than listing them flat.

    Three decisions worth stating, because each could reasonably go the other
    way and the tests pin all three:

    * **First-appearance order, not alphabetical.** Jinja's `groupby` (and
      itertools') sorts by the key, which would silently reshuffle an order the
      buyer typed deliberately. Groups appear in the order their first line
      does.
    * **Line numbers are NOT renumbered.** The paper has to tie back to the
      record; renumbering would print line 3 as line 1.
    * **Undescribed lines form a real group under the empty key**, so they still
      print. The template decides not to draw a heading for that one -- dropping
      them here would silently lose billable lines off a supplier's copy.

    A NULL amount counts as zero: a service line can legitimately carry none.
    """
    groups = {}
    order = []
    for li in sorted(line_items, key=lambda x: (x.line_number or 0)):
        key = (li.description or '').strip()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(li)
    return [(key, groups[key],
             sum((i.amount or Decimal('0')) for i in groups[key]))
            for key in order]


def grouped_lines_for_overlay(line_items):
    """[(item, show_description), ...] for the PRE-PRINTED overlay.

    Owner directive 2026-08-21: group the overlay by Description too.

    The overlay is not a table. Each column is an absolutely-positioned stack of
    fixed-height cells, and the columns line up ONLY because every stack holds
    the same number of rows (see print_preprinted.html: "all share the band top
    and rowHeight so rows align").

    So grouping cannot be done the way the standard printout does it. Heading
    and subtotal rows would consume boxes on the client's real pre-printed
    stationery and, unless inserted identically into every stack, would drift
    the columns down the page relative to the physical form -- a defect you only
    discover on paper.

    Grouping is therefore expressed the way a pre-printed form expresses it: the
    SAME rows, reordered so each group sits together, with the Description
    printed ONCE at the top of its group and blank beneath. Row count is
    unchanged, so alignment is structurally untouched.

    Only the DESCRIPTION is de-duplicated -- blanking a repeated quantity or
    amount would understate the order on the supplier's copy.
    """
    rows = []
    for _key, items, _subtotal in group_lines_by_description(line_items):
        for n, item in enumerate(items):
            rows.append((item, n == 0))
    return rows


# Row kinds emitted by overlay_rows(). Strings, not an enum, because the only
# consumer is a Jinja template comparing them.
OVERLAY_HEADING = 'heading'
OVERLAY_ITEM = 'item'
OVERLAY_END = 'end'

# Verbatim from the client's legacy pad, PO 00984: spaced hyphens, upper case.
NOTHING_FOLLOWS = '- NOTHING FOLLOWS -'


def overlay_rows(line_items):
    """[(kind, payload), ...] -- every ROW the PRE-PRINTED overlay draws.

    kind is OVERLAY_HEADING (payload: the remark text), OVERLAY_ITEM (payload: the
    PurchaseOrderItem) or OVERLAY_END (payload: None -- the NOTHING FOLLOWS
    terminator).

    HISTORY, because this reverses a documented decision. Until 2026-08-31
    grouped_lines_for_overlay returned one row per LINE and deliberately drew NO
    heading rows. The reasoning was sound and still is: the overlay is not a table,
    each column is an absolutely-positioned stack of fixed-height cells, and the
    columns line up ONLY because every stack holds the same number of rows. A heading
    inserted into one stack and not the others drifts that column down the page
    relative to the physical pre-printed boxes -- a defect you only find on paper.

    The client's own legacy pad prints the remark as a heading ABOVE its items and
    they asked for parity (owner directive 2026-08-31, annotated scan of PO 00984).
    The alignment constraint has NOT been abandoned -- it is met differently. This
    function emits the ROW LIST, and every column stack renders exactly one cell per
    row in it, blank wherever a column has nothing to say on that row. The stacks are
    therefore still equal-length BY CONSTRUCTION, which is the property that actually
    protects registration. What changed is only that the row count is no longer equal
    to the line count. tests/integration/test_po_overlay_grouped_render.py pins both
    halves.

    Still NO subtotal rows: the standard form has them, the pre-printed pad has no box
    for them, and nobody asked.

    Lines with no description form a real group under the empty key and print with no
    heading -- dropping them would silently lose billable lines off a supplier's copy.
    The terminator is emitted only for a non-empty order; "- NOTHING FOLLOWS -" under
    nothing of its own is its own kind of wrong.
    """
    rows = []
    for key, items, _subtotal in group_lines_by_description(line_items):
        if key:
            rows.append((OVERLAY_HEADING, key))
        for item in items:
            rows.append((OVERLAY_ITEM, item))
    if rows:
        rows.append((OVERLAY_END, None))
    return rows


def next_po_signatories_for(user_id):
    """{'prepared_by': ..., 'checked_by': ..., 'approved_by': ...} carried
    forward from THIS purchaser's own last order.

    Scoped by purchaser for the same reason next_po_number_for is: this client
    runs two purchasers, each holding her own pre-printed pad, and each routes
    her orders past different people. A company-wide setting would hand one
    purchaser the other's signatories.

    'Last' is by id, not by order_date -- a backdated order is still the most
    recently ENTERED one, and it is the last thing this purchaser typed that she
    expects to see repeated.

    Returns blanks (never None, never a placeholder) when this purchaser has no
    prior order: her first PO is typed from scratch, and a blank prints an empty
    ruled line to sign by hand.
    """
    blank = {f: '' for f in SIGNATORY_FIELDS}
    if not user_id:
        return blank
    last = (PurchaseOrder.query
            .filter(PurchaseOrder.created_by_id == user_id)
            .order_by(PurchaseOrder.id.desc())
            .first())
    if last is None:
        return blank
    return {f: (getattr(last, f) or '') for f in SIGNATORY_FIELDS}


def next_po_number_for(user_id, branch_id=None):
    """Suggest the next number off THIS purchaser's own pre-printed PO pad.

    The client runs two purchasers, each holding her own physical pad, and the
    two pads' number ranges NEVER overlap. generate_po_number()'s global max is
    therefore guaranteed to land outside the other purchaser's pad -- and, being
    restricted to purely-numeric numbers, it cannot even see a pad marker like
    '00001E' at all.

    The digit part is incremented as a NUMBER while the zero-padded width and
    the marker survive verbatim: '00001E' -> '00002E', '00099E' -> '00100E',
    '99999E' -> '100000E' (width grows naturally on overflow).

    Falls back to generate_po_number() when this purchaser has no usable prior
    PO -- her very first entry has nothing to infer from, and the number is
    typed off the paper form anyway. This function only ever produces a
    SUGGESTION or a starting point; po_number stays user-entered and unique.

    Composition with per-branch numbering scope -- PERSON FIRST, branch only
    when the person is unknown to the series. The pad belongs to a purchaser (a
    physical booklet in her hands), not to a branch: filtering her own POs by
    branch as well would split ONE pad into two series and hand her two
    different suggestions off the same paper. So the query below stays scoped by
    created_by_id alone, and branch_id is forwarded only to the two
    generate_po_number() fallbacks, which is exactly where the purchaser has no
    series of her own and the company's numbering policy is the right authority.
    Under 'company' scope branch_id is ignored entirely.
    """
    if not user_id:
        return generate_po_number(branch_id)
    rows = (db.session.query(PurchaseOrder.po_number)
            .filter(PurchaseOrder.created_by_id == user_id).all())
    best = None
    for (number,) in rows:
        m = _PO_NUMBER_RE.match(number) if number else None
        if not m:
            continue
        digits, marker = m.group(1), m.group(2)
        value = int(digits)
        if best is None or value > best[0]:
            best = (value, len(digits), marker)
    if best is None:
        return generate_po_number(branch_id)
    value, width, marker = best
    # Never offer a number the save will refuse. The pad design above assumes the
    # two pads' ranges do not overlap; PhilGen's real data broke that assumption
    # (four orders, all plain numeric, one branch, no markers), so the form handed
    # two of its three users a number already in use -- deterministically, on every
    # attempt, which is why retrying never helped the purchaser
    # (BUG-PO-CREATE-DROPS-LINES-ON-VALIDATION-REJECT).
    #
    # This walks HER OWN series past the collision rather than falling back to the
    # global maximum: staying on her pad is the whole point of the function, and a
    # global answer would drop her onto the other purchaser's range -- the exact
    # thing the pad logic exists to avoid. Width and marker are carried through
    # unchanged, so '00002E' skips to '00003E', never to a bare '00003'.
    taken = {n for (n,) in db.session.query(PurchaseOrder.po_number).all() if n}
    candidate = value + 1
    while f'{candidate:0{width}d}{marker}' in taken:
        candidate += 1
    return f'{candidate:0{width}d}{marker}'
