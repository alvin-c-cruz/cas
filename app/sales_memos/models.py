"""Sales Memo models -- Credit Memo (Sales Returns) and Debit Note (undercharges).

Two BIR documents sharing one model via `memo_type` ('credit' | 'debit'). A memo
references ONE posted Sales Invoice, line-level, and adjusts AR. Line math mirrors
SalesInvoiceItem: VAT-inclusive extraction, WHT on Net-of-ROUNDED-VAT. A credit memo
REVERSES the referenced portion of the SI's revenue/VAT/WHT; a debit memo repeats it.
Accounting happens in the view JE builder; the model only holds/derives amounts.
"""
from decimal import Decimal

from app import db
from app.utils import ph_now

MEMO_TYPES = ('credit', 'debit')
DESTINATIONS = ('ar', 'cash_refund', 'customer_credit')
MEMO_PREFIX = {'credit': 'CM', 'debit': 'DM'}


class SalesMemo(db.Model):
    __tablename__ = 'sales_memos'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    memo_type = db.Column(db.String(10), nullable=False, index=True)   # 'credit' | 'debit'
    memo_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    memo_date = db.Column(db.Date, nullable=False, index=True)

    # The referenced posted Sales Invoice + snapshot.
    sales_invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'),
                                 nullable=False, index=True)
    sales_invoice = db.relationship('SalesInvoice', foreign_keys=[sales_invoice_id])
    original_invoice_number = db.Column(db.String(50), nullable=False)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer')
    customer_name = db.Column(db.String(200), nullable=False)
    customer_tin = db.Column(db.String(20))
    customer_address = db.Column(db.Text)

    reason = db.Column(db.String(500), nullable=False)      # BIR-required reason for the memo
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text, nullable=False, default='')

    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)      # VAT-inclusive sum
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    withholding_tax_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # subtotal - WHT

    # Where the credit/charge lands: 'ar' (referenced SI balance), 'cash_refund', 'customer_credit'.
    destination = db.Column(db.String(20), default='ar', nullable=False)
    cash_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    cash_account = db.relationship('Account', foreign_keys=[cash_account_id])

    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)  # draft|posted|voided

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    voided_at = db.Column(db.DateTime)
    void_reason = db.Column(db.String(255))

    line_items = db.relationship('SalesMemoItem', backref='memo', lazy='select',
                                 cascade='all, delete-orphan',
                                 order_by='SalesMemoItem.line_number')

    def calculate_totals(self):
        """Mirror SalesInvoice.calculate_totals: subtotal is the VAT-inclusive line sum,
        total is subtotal net of WHT."""
        self.subtotal = sum((Decimal(str(li.line_total or 0)) for li in self.line_items),
                            Decimal('0.00'))
        self.vat_amount = sum((Decimal(str(li.vat_amount or 0)) for li in self.line_items),
                              Decimal('0.00'))
        self.withholding_tax_amount = sum((Decimal(str(li.wt_amount or 0)) for li in self.line_items),
                                          Decimal('0.00'))
        self.total_amount = self.subtotal - self.withholding_tax_amount

    def to_dict(self):
        return {
            'id': self.id, 'memo_type': self.memo_type, 'memo_number': self.memo_number,
            'memo_date': self.memo_date.isoformat() if self.memo_date else None,
            'status': self.status, 'destination': self.destination,
            'original_invoice_number': self.original_invoice_number,
            'customer_name': self.customer_name,
            'subtotal': float(self.subtotal) if self.subtotal is not None else 0.0,
            'vat_amount': float(self.vat_amount) if self.vat_amount is not None else 0.0,
            'withholding_tax_amount': (float(self.withholding_tax_amount)
                                       if self.withholding_tax_amount is not None else 0.0),
            'total_amount': float(self.total_amount) if self.total_amount is not None else 0.0,
        }


class SalesMemoItem(db.Model):
    __tablename__ = 'sales_memo_items'

    id = db.Column(db.Integer, primary_key=True)
    sales_memo_id = db.Column(db.Integer, db.ForeignKey('sales_memos.id'), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)

    # The original SI line this memo line adjusts.
    sales_invoice_item_id = db.Column(db.Integer, db.ForeignKey('sales_invoice_items.id'),
                                      nullable=False, index=True)
    sales_invoice_item = db.relationship('SalesInvoiceItem', foreign_keys=[sales_invoice_item_id])

    quantity = db.Column(db.Numeric(15, 4), nullable=True)
    unit_price = db.Column(db.Numeric(15, 2), nullable=True)
    uom_text = db.Column(db.String(20), nullable=True)
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    unit_of_measure = db.relationship('UnitOfMeasure')
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product = db.relationship('Product')

    amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)       # VAT-inclusive
    line_total = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)   # == amount
    vat_category = db.Column(db.String(100))
    vat_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)
    withholding_tax = db.relationship('WithholdingTax', foreign_keys=[wt_id])
    wt_rate = db.Column(db.Numeric(5, 2), nullable=True)
    wt_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)  # SI line's revenue account
    account = db.relationship('Account', foreign_keys=[account_id])

    def calculate_amounts(self):
        """Extract VAT from the VAT-inclusive amount; WHT on Net-of-ROUNDED-VAT.
        Mirrors SalesInvoiceItem.calculate_amounts exactly."""
        if self.quantity is not None and self.unit_price is not None:
            q = Decimal(str(self.quantity)); up = Decimal(str(self.unit_price))
            if q > 0 and up > 0:
                self.amount = (q * up).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
        vat_rate = Decimal(str(self.vat_rate)) if self.vat_rate else Decimal('0')
        amount = Decimal(str(self.amount)) if self.amount else Decimal('0')
        net_base = amount / (1 + vat_rate / Decimal('100')) if vat_rate > 0 else amount
        self.line_total = amount
        self.vat_amount = (amount - net_base).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
        net_of_vat = amount - self.vat_amount
        wt_rate = Decimal(str(self.wt_rate)) if self.wt_rate else Decimal('0')
        self.wt_amount = (net_of_vat * wt_rate / Decimal('100')).quantize(
            Decimal('0.01'), rounding='ROUND_HALF_UP')

    def to_dict(self):
        return {
            'id': self.id, 'line_number': self.line_number,
            'sales_invoice_item_id': self.sales_invoice_item_id,
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
            'vat_amount': float(self.vat_amount) if self.vat_amount is not None else 0.0,
            'line_total': float(self.line_total) if self.line_total is not None else 0.0,
            'account_id': self.account_id,
            'wt_id': self.wt_id,
            'wt_rate': float(self.wt_rate) if self.wt_rate is not None else None,
            'wt_amount': float(self.wt_amount) if self.wt_amount is not None else 0.0,
        }


def generate_memo_number(memo_type):
    """Next CM-/DM-YYYY-MM-#### for the current PH month (mirror generate_quotation_number).
    Each memo_type keeps its own monthly sequence."""
    prefix_code = MEMO_PREFIX[memo_type]
    today = ph_now().date()
    prefix = f"{prefix_code}-{today.year:04d}-{today.month:02d}-"
    rows = (SalesMemo.query.filter(SalesMemo.memo_number.like(prefix + '%'))
            .with_entities(SalesMemo.memo_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
