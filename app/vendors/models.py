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

    # Default VAT type: VATOG (VAT on Goods) 12%, VATSV (VAT on Services) 12%
    default_vat = db.Column(db.String(50))

    # Default Withholding Tax: WC158 (2%), WC160 (1%), WC100 (5%), etc.
    default_wt = db.Column(db.String(50))

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
            'default_vat': self.default_vat,
            'default_wt': self.default_wt,
            'address': self.address,
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
