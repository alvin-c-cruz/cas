from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned
from decimal import Decimal


class CashReceiptVoucher(RowVersioned, db.Model):
    __tablename__ = 'cash_receipt_vouchers'

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    crv_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    crv_date = db.Column(db.Date, nullable=False, index=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer', backref='cash_receipts')
    customer_name = db.Column(db.String(200), nullable=False)
    customer_tin = db.Column(db.String(20))

    payment_method = db.Column(db.String(20), nullable=False, default='cash')
    check_number = db.Column(db.String(50))
    check_date = db.Column(db.Date)
    check_bank = db.Column(db.String(100))

    cash_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    cash_account = db.relationship('Account', foreign_keys=[cash_account_id])

    notes = db.Column(db.Text, nullable=False, default='')

    total_ar_applied = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_revenue = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_vat = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_wt = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    vat_override = db.Column(db.Boolean, default=False, nullable=False)
    wt_override = db.Column(db.Boolean, default=False, nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_crvs')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_crvs')
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_crvs')

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    voided_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    void_reason = db.Column(db.String(255))
    cancel_reason = db.Column(db.String(500))

    ar_lines = db.relationship('CRVArLine', backref='crv', lazy='select',
                               cascade='all, delete-orphan',
                               order_by='CRVArLine.line_number')
    revenue_lines = db.relationship('CRVRevenueLine', backref='crv', lazy='select',
                                    cascade='all, delete-orphan',
                                    order_by='CRVRevenueLine.line_number')

    def __repr__(self):
        return f'<CashReceiptVoucher {self.crv_number}>'

    def calculate_totals(self):
        self.total_ar_applied = sum(
            (Decimal(str(l.amount_applied)) for l in self.ar_lines),
            Decimal('0.00')
        )
        auto_revenue = Decimal('0.00')
        auto_vat = Decimal('0.00')
        auto_wt = Decimal('0.00')
        for line in self.revenue_lines:
            auto_revenue += Decimal(str(line.line_total))
            auto_vat += Decimal(str(line.vat_amount))
            auto_wt += Decimal(str(line.wt_amount or 0))
        self.total_revenue = auto_revenue
        if not self.vat_override:
            self.total_vat = auto_vat
        if not self.wt_override:
            self.total_wt = auto_wt
        self.total_amount = self.total_ar_applied + self.total_revenue - self.total_wt

    def to_dict(self):
        return {
            'id': self.id,
            'crv_number': self.crv_number,
            'crv_date': self.crv_date.isoformat() if self.crv_date else None,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'payment_method': self.payment_method,
            'total_ar_applied': float(self.total_ar_applied),
            'total_revenue': float(self.total_revenue),
            'total_vat': float(self.total_vat),
            'total_wt': float(self.total_wt),
            'total_amount': float(self.total_amount),
            'status': self.status,
        }


class CRVArLine(db.Model):
    __tablename__ = 'crv_ar_lines'

    id = db.Column(db.Integer, primary_key=True)
    crv_id = db.Column(db.Integer, db.ForeignKey('cash_receipt_vouchers.id'),
                       nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=False)
    sales_invoice = db.relationship('SalesInvoice', foreign_keys=[invoice_id])
    invoice_number = db.Column(db.String(50), nullable=False)
    original_balance = db.Column(db.Numeric(15, 2), nullable=False)
    amount_applied = db.Column(db.Numeric(15, 2), nullable=False)

    def __repr__(self):
        return f'<CRVArLine crv={self.crv_id} inv={self.invoice_number}>'

    def to_dict(self):
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'invoice_number': self.invoice_number,
            'original_balance': float(self.original_balance),
            'amount_applied': float(self.amount_applied),
        }


class CRVRevenueLine(db.Model):
    __tablename__ = 'crv_revenue_lines'

    id = db.Column(db.Integer, primary_key=True)
    crv_id = db.Column(db.Integer, db.ForeignKey('cash_receipt_vouchers.id'),
                       nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    quantity = db.Column(db.Numeric(15, 4), nullable=True)
    unit_price = db.Column(db.Numeric(15, 2), nullable=True)
    uom_text = db.Column(db.String(20), nullable=True)
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    unit_of_measure = db.relationship('UnitOfMeasure')
    product = db.relationship('Product')
    vat_category = db.Column(db.String(100))
    vat_rate = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    line_total = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account = db.relationship('Account')
    wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)
    withholding_tax = db.relationship('WithholdingTax', foreign_keys=[wt_id])
    wt_rate = db.Column(db.Numeric(5, 2), nullable=True)
    wt_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'),
                          server_default='0.00', nullable=False)

    def __repr__(self):
        return f'<CRVRevenueLine crv={self.crv_id} line={self.line_number}>'

    def calculate_amounts(self):
        # Derived amount when itemized: amount = qty × unit_price (VAT-inclusive).
        if self.quantity is not None and self.unit_price is not None:
            q = Decimal(str(self.quantity)); up = Decimal(str(self.unit_price))
            if q > 0 and up > 0:
                self.amount = (q * up).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
        vat_rate = Decimal(str(self.vat_rate)) if self.vat_rate else Decimal('0')
        if vat_rate > 0:
            net_base = Decimal(str(self.amount)) / (1 + vat_rate / Decimal('100'))
        else:
            net_base = Decimal(str(self.amount))
        self.line_total = Decimal(str(self.amount))
        self.vat_amount = (Decimal(str(self.amount)) - net_base).quantize(
            Decimal('0.01'), rounding='ROUND_HALF_UP')
        # WHT base is Net of VAT = Gross - rounded VAT (owner/RIC formula),
        # NOT the unrounded Gross/1.12 — they differ a centavo on residual lines.
        net_of_vat = Decimal(str(self.amount)) - self.vat_amount
        wt_rate = Decimal(str(self.wt_rate)) if self.wt_rate else Decimal('0')
        self.wt_amount = (net_of_vat * wt_rate / Decimal('100')).quantize(
            Decimal('0.01'), rounding='ROUND_HALF_UP')

    def to_dict(self):
        return {
            'id': self.id,
            'line_number': self.line_number,
            'description': self.description,
            'amount': float(self.amount),
            'quantity': float(self.quantity) if self.quantity is not None else None,
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'uom_text': self.uom_text,
            'unit_of_measure_id': self.unit_of_measure_id,
            'uom_code': self.unit_of_measure.code if self.unit_of_measure else None,
            'uom_name': self.unit_of_measure.name if self.unit_of_measure else None,
            'uom_display': (self.unit_of_measure.code if self.unit_of_measure else self.uom_text),
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else None,
            'product_name': self.product.name if self.product else None,
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate),
            'line_total': float(self.line_total),
            'vat_amount': float(self.vat_amount),
            'account_id': self.account_id,
            'wt_id': self.wt_id,
            'wt_code': self.withholding_tax.code if self.withholding_tax else None,
            'wt_rate': float(self.wt_rate) if self.wt_rate is not None else None,
            'wt_amount': float(self.wt_amount),
        }
