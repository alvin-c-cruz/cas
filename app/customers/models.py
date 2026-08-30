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

    # Record lock. Staff may maintain customer data (owner directive 2026-08-30 --
    # they could already CREATE one through quick-add but not correct it, and
    # vendors have allowed staff to edit all along); an approver freezes a record
    # once it is settled. Provenance is stored alongside the flag because "who
    # froze this, and when" is the question a bare boolean cannot answer.
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    locked_at = db.Column(db.DateTime, nullable=True)

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
    locked_by = db.relationship('User', foreign_keys=[locked_by_id])

    # -- record lock ------------------------------------------------------
    #
    # ONE spelling of each rule, on the model, because the view and the template
    # both need it: a route that refuses and a button that still renders is the
    # delete_approved_email shape, and that is exactly the defect this feature
    # inherits (the Edit control is currently rendered unconditionally). Two
    # copies of the predicate would drift the moment either side changed.

    @staticmethod
    def _is_approver(user):
        """Accountant, chief accountant or admin -- the roles `edit` already
        required before staff were let in. `has_full_access` covers admin AND
        chief accountant, so it is not spelled out twice."""
        return bool(user is not None
                    and getattr(user, 'is_authenticated', False)
                    and (user.role == 'accountant' or user.has_full_access))

    def can_be_edited_by(self, user):
        """A lock removes STAFF's write access and never restricts an approver.

        An approver keeps write access THROUGH the lock deliberately: freezing a
        record must not make a typo in it uncorrectable, which would leave the
        database as the only way to fix one.
        """
        if self._is_approver(user):
            return True
        if user is None or not getattr(user, 'is_authenticated', False):
            return False
        return (not self.is_locked) and user.role == 'staff'

    def can_manage_lock_by(self, user):
        """Who may lock and unlock: the same three roles that can edit through a
        lock. If staff could lift it, it would protect nothing."""
        return self._is_approver(user)

    def lock(self, user):
        from app.utils import ph_now
        self.is_locked = True
        self.locked_by_id = getattr(user, 'id', None)
        self.locked_at = ph_now()

    def unlock(self):
        """Clears the provenance too -- leaving a stale locked_by/locked_at on an
        unlocked record would read as "frozen by X" long after it was lifted."""
        self.is_locked = False
        self.locked_by_id = None
        self.locked_at = None

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
