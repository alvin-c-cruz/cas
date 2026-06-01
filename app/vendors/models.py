"""
Vendor model for supplier/vendor management
"""
from app import db
from app.utils import ph_now


# Association table for many-to-many relationship between vendors and withholding taxes
vendor_withholding_taxes = db.Table('vendor_withholding_taxes',
    db.Column('vendor_id', db.Integer, db.ForeignKey('vendors.id'), primary_key=True),
    db.Column('withholding_tax_id', db.Integer, db.ForeignKey('withholding_tax.id'), primary_key=True)
)


class Vendor(db.Model):
    """
    Vendor/Supplier model for managing business partners.

    Fields based on Philippine business requirements:
    - TIN: Tax Identification Number (BIR requirement)
    - Terms: Payment terms (Net 15, Net 30, Net 45, etc.)
    - Default VAT: VATOG (VAT on Goods) 12%, VATSV (VAT on Services) 12%
    - Default WT: Withholding Tax (WC158, WC160, WC100, etc.)
    """
    __tablename__ = 'vendors'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    contact_person = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    tin = db.Column(db.String(20))  # Tax Identification Number

    # Payment terms (Net 15, Net 30, Net 45, etc.)
    payment_terms = db.Column(db.String(50), default='Net 30')

    # Address and other details
    address = db.Column(db.Text)
    email = db.Column(db.String(120))

    # Check payee name (for printing on checks)
    check_payee_name = db.Column(db.String(200))

    # Postal code
    postal_code = db.Column(db.String(20))

    # Default VAT Category
    default_vat_category = db.Column(db.String(100))

    # Withholding Tax checkboxes (DEPRECATED - kept for backward compatibility during migration)
    # These will be removed after migrating to the many-to-many relationship
    wt_wc010 = db.Column(db.Boolean, default=False)  # Prof. Fees - Individuals (10%)
    wt_wc011 = db.Column(db.Boolean, default=False)  # Prof. Fees - Corporations (15%)
    wt_wc100 = db.Column(db.Boolean, default=False)  # Contractors & Subcontractors (2%)
    wt_wc158 = db.Column(db.Boolean, default=False)  # Purchases of Goods (1%)

    # Dynamic withholding tax relationship (many-to-many)
    withholding_taxes = db.relationship('WithholdingTax',
                                       secondary=vendor_withholding_taxes,
                                       backref=db.backref('vendors', lazy='dynamic'))

    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=ph_now)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)

    def __repr__(self):
        return f'<Vendor {self.code} - {self.name}>'

    def to_dict(self):
        """Convert vendor to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'contact_person': self.contact_person,
            'phone': self.phone,
            'tin': self.tin,
            'email': self.email,
            'payment_terms': self.payment_terms,
            'address': self.address,
            'check_payee_name': self.check_payee_name,
            'postal_code': self.postal_code,
            'default_vat_category': self.default_vat_category,
            'wt_wc010': self.wt_wc010,
            'wt_wc011': self.wt_wc011,
            'wt_wc100': self.wt_wc100,
            'wt_wc158': self.wt_wc158,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
