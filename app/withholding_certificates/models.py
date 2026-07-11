"""Register of BIR 2307 certificates RECEIVED from customers (payee side).

The SAWT asserts creditable withholding we hold a certificate for -- so it renders
from THIS register, never from the books. A reconciliation view diffs the register
against what our SI/CRV say customers withheld (wht_lines payee side).

Branch-scoped per the day-one rule; the SAWT aggregates across branches because
filing is company-wide (per-TIN).
"""
from app import db
from app.utils import ph_now


class WithholdingCertificateReceived(db.Model):
    __tablename__ = 'withholding_certificates_received'

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer', foreign_keys=[customer_id])

    certificate_number = db.Column(db.String(50), nullable=False)
    date_received = db.Column(db.Date, nullable=False)

    # The quarter the payor certified (period covered by the 2307).
    period_from = db.Column(db.Date, nullable=False)
    period_to = db.Column(db.Date, nullable=False)

    wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=False, index=True)
    withholding_tax = db.relationship('WithholdingTax', foreign_keys=[wt_id])

    income_payment = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    tax_withheld = db.Column(db.Numeric(15, 2), nullable=False, default=0)

    attachment_path = db.Column(db.String(255), nullable=True)   # scan of the physical 2307
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    created_by = db.Column(db.String(80), nullable=True)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    updated_by = db.Column(db.String(80), nullable=True)

    def __repr__(self):
        return f'<WithholdingCertificateReceived {self.certificate_number}>'

    def to_dict(self):
        return {
            'id': self.id,
            'branch_id': self.branch_id,
            'customer_id': self.customer_id,
            'certificate_number': self.certificate_number,
            'date_received': self.date_received.isoformat() if self.date_received else None,
            'period_from': self.period_from.isoformat() if self.period_from else None,
            'period_to': self.period_to.isoformat() if self.period_to else None,
            'wt_id': self.wt_id,
            'income_payment': float(self.income_payment) if self.income_payment is not None else None,
            'tax_withheld': float(self.tax_withheld) if self.tax_withheld is not None else None,
            'attachment_path': self.attachment_path,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by': self.updated_by,
        }
