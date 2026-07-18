"""Product / Item master — base (pre-inventory) keystone of R-01/R-02/R-03.

Per-company optional module. `standard_cost` was added by R-03a slice 2 (Income
Statement by Product Line) as an always-visible planning-cost figure. R-03 Slice 1
adds track_inventory/costing_method/reorder_level -- additive, nullable-except-
track_inventory columns gated by the `inventory` module, and reuses R-03a's
`standard_cost` (narrowed to Numeric(15,2)) as the value required alongside
costing_method when track_inventory is checked. See
docs/superpowers/specs/2026-07-19-inventory-item-fields-design.md and
docs/superpowers/plans/2026-07-19-product-standard-cost-collision-decision.md.
"""
from app import db
from app.utils import ph_now

COSTING_METHODS = ('moving_average', 'fifo', 'standard', 'lifo', 'specific_identification')


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    job_order_name = db.Column(db.String(200), nullable=True)
    default_unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    default_unit_price = db.Column(db.Numeric(15, 2), nullable=True)   # VAT-inclusive
    default_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('product_categories.id'), nullable=True)
    standard_cost = db.Column(db.Numeric(15, 2), nullable=True)
    track_inventory = db.Column(db.Boolean, default=False, nullable=False)
    costing_method = db.Column(db.String(30), nullable=True)
    reorder_level = db.Column(db.Numeric(15, 2), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    default_unit_of_measure = db.relationship('UnitOfMeasure', foreign_keys=[default_unit_of_measure_id])
    default_account = db.relationship('Account', foreign_keys=[default_account_id])
    category = db.relationship('ProductCategory', foreign_keys=[category_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<Product {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id, 'code': self.code, 'name': self.name,
            'description': self.description,
            'job_order_name': self.job_order_name,
            'default_uom_id': self.default_unit_of_measure_id,
            'default_uom_code': self.default_unit_of_measure.code if self.default_unit_of_measure else None,
            'default_unit_price': float(self.default_unit_price) if self.default_unit_price is not None else None,
            'default_account_id': self.default_account_id,
            'category_id': self.category_id,
            'standard_cost': float(self.standard_cost) if self.standard_cost is not None else None,
            'track_inventory': self.track_inventory,
            'costing_method': self.costing_method,
            'reorder_level': float(self.reorder_level) if self.reorder_level is not None else None,
            'is_active': self.is_active,
        }
