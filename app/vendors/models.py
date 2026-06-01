"""
Vendor model for supplier/vendor management
"""
from app import db
from app.utils import ph_now


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

    # Check payee name (defaults to vendor name if blank)
    check_payee_name = db.Column(db.String(200))

    # Postal code
    postal_code = db.Column(db.String(20))

    # Default VAT Category: Other Goods (12%), Services (12%), etc.
    default_vat_category = db.Column(db.String(100))

    # Default Withholding Tax - Multiple checkboxes stored as JSON
    # WC010: Prof. Fees - Individuals (10%)
    # WC011: Prof. Fees - Corporations (15%)
    # WC100: Contractors & Subcontractors (2%)
    # WC158: Purchases of Goods (1%)
    wt_wc010 = db.Column(db.Boolean, default=False)  # Prof. Fees - Individuals
    wt_wc011 = db.Column(db.Boolean, default=False)  # Prof. Fees - Corporations
    wt_wc100 = db.Column(db.Boolean, default=False)  # Contractors & Subcontractors
    wt_wc158 = db.Column(db.Boolean, default=False)  # Purchases of Goods

    # Address and other details
    address = db.Column(db.Text)
    email = db.Column(db.String(120))

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
            'payment_terms': self.payment_terms,
            'check_payee_name': self.check_payee_name,
            'postal_code': self.postal_code,
            'default_vat_category': self.default_vat_category,
            'wt_wc010': self.wt_wc010,
            'wt_wc011': self.wt_wc011,
            'wt_wc100': self.wt_wc100,
            'wt_wc158': self.wt_wc158,
            'address': self.address,
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
