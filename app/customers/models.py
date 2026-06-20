"""
Customer models for CAS
"""
from app import db
from app.utils import ph_now


# Association table for the many-to-many between customers and withholding taxes
# (mirrors vendor_withholding_taxes in app/vendors/models.py).
customer_withholding_taxes = db.Table('customer_withholding_taxes',
    db.Column('customer_id', db.Integer, db.ForeignKey('customers.id'), primary_key=True),
    db.Column('withholding_tax_id', db.Integer, db.ForeignKey('withholding_tax.id'), primary_key=True),
)


class Customer(db.Model):
    """Customer/Client master table (shared across branches)"""
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    contact_person = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    tin = db.Column(db.String(50))
    payment_terms = db.Column(db.String(50))
    address = db.Column(db.Text)
    postal_code = db.Column(db.String(20))

    # VAT and WT for customer transactions
    default_vat_category = db.Column(db.String(100))
    default_wt_code = db.Column(db.String(20))

    # Many-to-many WHT list — scopes the SI/CRV line-WT dropdown (parity with Vendor).
    # default_wt_code is kept for back-compat (exports/audit); the list is the new source of truth.
    withholding_taxes = db.relationship('WithholdingTax',
                                        secondary=customer_withholding_taxes,
                                        backref=db.backref('customers', lazy='dynamic'))

    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Audit fields
    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='customers_created')
    updated_by = db.relationship('User', foreign_keys=[updated_by_id], backref='customers_updated')

    @property
    def withholding_taxes_str(self):
        """Comma-joined WHT codes for audit snapshots and exports."""
        return ', '.join(wt.code for wt in self.withholding_taxes)

    def __repr__(self):
        return f'<Customer {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'contact_person': self.contact_person,
            'phone': self.phone,
            'email': self.email,
            'tin': self.tin,
            'payment_terms': self.payment_terms,
            'address': self.address,
            'postal_code': self.postal_code,
            'default_vat_category': self.default_vat_category,
            'default_wt_code': self.default_wt_code,
            'withholding_taxes': [
                {'id': w.id, 'code': w.code, 'name': w.name, 'rate': float(w.rate)}
                for w in self.withholding_taxes
            ],
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
