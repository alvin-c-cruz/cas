"""Bill of Materials — R-07's shared spine (Wave 0). One BillOfMaterial per
Product (1:1, immutable link), regardless of manufacturing_mode: the same
header/line shape serves both the discrete (Work Order/routing) and process
(Production Run/equivalent-units) tracks built on top of it later.
See docs/superpowers/specs/2026-07-19-manufacturing-r07-design.md."""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

MANUFACTURING_MODES = ('discrete', 'process')


class BillOfMaterial(RowVersioned, db.Model):
    __tablename__ = 'bills_of_material'

    id = db.Column(db.Integer, primary_key=True)
    # 1:1, globally unique, immutable after creation (edit form never exposes it)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, unique=True)
    manufacturing_mode = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    product = db.relationship('Product', foreign_keys=[product_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    lines = db.relationship('BillOfMaterialLine', backref='bom', cascade='all, delete-orphan',
                            order_by='BillOfMaterialLine.line_number')

    def __repr__(self):
        return f'<BillOfMaterial product_id={self.product_id} mode={self.manufacturing_mode}>'


class BillOfMaterialLine(db.Model):
    __tablename__ = 'bill_of_material_lines'

    id = db.Column(db.Integer, primary_key=True)
    bom_id = db.Column(db.Integer, db.ForeignKey('bills_of_material.id'), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    component_product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity_per = db.Column(db.Numeric(15, 4), nullable=False)
    uom_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)

    component_product = db.relationship('Product', foreign_keys=[component_product_id])
    uom = db.relationship('UnitOfMeasure', foreign_keys=[uom_id])

    def to_dict(self):
        return {
            'id': self.id,
            'component_product_id': self.component_product_id,
            'component_code': self.component_product.code if self.component_product else None,
            'component_name': self.component_product.name if self.component_product else None,
            'quantity_per': float(self.quantity_per),
            'uom_id': self.uom_id,
            'uom_code': self.uom.code if self.uom else None,
        }
