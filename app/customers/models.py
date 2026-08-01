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
    # The code this customer uses to identify US as their vendor in their own
    # system (e.g. MySan's "200100" for Rowell) -- distinct from `code` above,
    # which is this app's own internal code for the customer. Optional: legacy
    # data shows it's only populated for some customers.
    vendor_code = db.Column(db.String(50), nullable=True)

    # VAT and WT for customer transactions
    default_vat_category = db.Column(db.String(100))
    default_wt_code = db.Column(db.String(20))

    # Many-to-many WHT list — scopes the SI/CRV line-WT dropdown (parity with Vendor).
    # default_wt_code is kept for back-compat (exports/audit); the list is the new source of truth.
    withholding_taxes = db.relationship('WithholdingTax',
                                        secondary=customer_withholding_taxes,
                                        backref=db.backref('customers', lazy='dynamic'))

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    po_required = db.Column(db.Boolean, default=False, nullable=False)

    # Default salesperson to auto-fill on Sales Orders for this customer (optional).
    default_salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    default_salesperson = db.relationship('Employee', foreign_keys=[default_salesperson_id])

    # Audit fields
    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='customers_created')
    updated_by = db.relationship('User', foreign_keys=[updated_by_id], backref='customers_updated')

    # Named delivery sites (e.g. warehouses) a customer's Sales Order lines can ship to.
    delivery_sites = db.relationship('CustomerDeliverySite', backref='customer',
                                     cascade='all, delete-orphan',
                                     order_by='CustomerDeliverySite.name')

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
            'vendor_code': self.vendor_code,
            'default_vat_category': self.default_vat_category,
            'default_wt_code': self.default_wt_code,
            'withholding_taxes': [
                {'id': w.id, 'code': w.code, 'name': w.name, 'rate': float(w.rate)}
                for w in self.withholding_taxes
            ],
            'is_active': self.is_active,
            'po_required': self.po_required,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CustomerDeliverySite(db.Model):
    """A named delivery site (e.g. warehouse) belonging to a Customer.

    Sales Order lines will later pick one of a customer's delivery sites plus a
    per-line delivery date. No `address` column (owner decision) and no DB-level
    unique constraint on (customer_id, name) -- legacy data is messy free text,
    a hard constraint could reject a valid re-entry of a typo-adjacent name.
    """
    __tablename__ = 'customer_delivery_sites'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=ph_now)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)

    def __repr__(self):
        return f'<CustomerDeliverySite {self.name} (customer_id={self.customer_id})>'

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'name': self.name,
            'is_active': self.is_active,
        }
