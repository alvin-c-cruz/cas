"""Sales Invoice for the EXTRA branch (SI-Extra).

EXTRA-branch sales carry NO VAT and NO WHT (owner-confirmed 2026-07-30,
cross-checked against the legacy accounting GL: every sales_x/sales_entry_x
entry is a bare 2-line JE -- Dr AR-Trade or Cash / Cr Sales revenue -- no
VAT/WHT accounts touched). This is a deliberately separate, lighter model
from app.sales_invoices.SalesInvoice rather than a VAT/WHT=zero row on that
table, so CORP's VAT/WHT machinery can never accidentally engage on an EXTRA
document.

invoice_number is always set equal to the legacy DR number it bills (owner
convention: "Extra use the same DR# for recording on SI") -- SalesInvoiceExtra
is a 1:1 companion to the DeliveryReceipt it invoices, not a batched/
consolidated document.
"""
from app import db
from app.utils import ph_now
from decimal import Decimal


class SalesInvoiceExtra(db.Model):
    __tablename__ = 'sales_invoices_extra'

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    invoice_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    invoice_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer', backref='sales_invoices_extra')
    customer_name = db.Column(db.String(200), nullable=False)
    customer_address = db.Column(db.Text)

    payment_terms = db.Column(db.String(50))
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text, nullable=False, default='')

    delivery_receipt_id = db.Column(db.Integer, db.ForeignKey('delivery_receipts.id'),
                                     unique=True, nullable=True)
    delivery_receipt = db.relationship('DeliveryReceipt', foreign_keys=[delivery_receipt_id])

    # No VAT/WHT columns by design -- subtotal == total_amount always.
    subtotal = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)

    # Per-transaction control-account overrides, same pattern as SalesInvoice --
    # nullable, posting engine falls back to get_control_account() when unset.
    ar_trade_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    ar_trade_account = db.relationship('Account', foreign_keys=[ar_trade_account_id])
    sales_revenue_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    sales_revenue_account = db.relationship('Account', foreign_keys=[sales_revenue_account_id])

    is_cash_sale = db.Column(db.Boolean, default=False, nullable=False)
    cash_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    cash_account = db.relationship('Account', foreign_keys=[cash_account_id])

    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    # Statuses: draft, posted, partially_paid, paid, cancelled, voided
    status = db.Column(db.String(20), default='draft', nullable=False, index=True)
    amount_paid = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)
    balance = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)

    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_sales_invoices_extra')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_sales_invoices_extra')
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_sales_invoices_extra')

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    voided_at = db.Column(db.DateTime)
    void_reason = db.Column(db.String(255))
    cancel_reason = db.Column(db.String(500), nullable=True)

    line_items = db.relationship('SalesInvoiceExtraItem', backref='invoice', lazy='select',
                                  cascade='all, delete-orphan',
                                  order_by='SalesInvoiceExtraItem.line_number')

    def __repr__(self):
        return f'<SalesInvoiceExtra {self.invoice_number}>'

    def calculate_totals(self):
        subtotal = Decimal('0.00')
        for item in self.line_items:
            subtotal += Decimal(str(item.amount))
        self.subtotal = subtotal
        self.total_amount = subtotal
        paid = self.amount_paid if self.amount_paid is not None else Decimal('0.00')
        self.balance = self.total_amount - Decimal(str(paid))


class SalesInvoiceExtraItem(db.Model):
    __tablename__ = 'sales_invoice_extra_items'

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices_extra.id'),
                            nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)

    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product = db.relationship('Product')
    quantity = db.Column(db.Numeric(15, 4), nullable=True)
    unit_price = db.Column(db.Numeric(15, 2), nullable=True)
    uom_text = db.Column(db.String(20), nullable=True)
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    unit_of_measure = db.relationship('UnitOfMeasure')

    # No VAT/WHT columns by design (see module docstring).
    amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)

    def __repr__(self):
        return f'<SalesInvoiceExtraItem {self.invoice_id}-{self.line_number}>'

    def calculate_amounts(self):
        if self.quantity is not None and self.unit_price is not None:
            self.amount = (Decimal(str(self.quantity)) * Decimal(str(self.unit_price))).quantize(Decimal('0.01'))
