"""Work Order — the discrete-track job-costing document header (R-07 Discrete
Track slice D2). On release, snapshots its BillOfMaterial's lines/operations
onto WorkOrderMaterial/WorkOrderOperation so a later BOM edit never disturbs a
job already released. See docs/superpowers/specs/2026-07-19-manufacturing-r07-design.md."""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

WO_STATUSES = ('draft', 'released', 'in_progress', 'completed', 'cancelled')
OP_STATUSES = ('pending', 'in_progress', 'complete')


class WorkOrder(RowVersioned, db.Model):
    __tablename__ = 'work_orders'

    id = db.Column(db.Integer, primary_key=True)
    wo_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    bom_id = db.Column(db.Integer, db.ForeignKey('bills_of_material.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    qty_to_produce = db.Column(db.Numeric(15, 4), nullable=False)
    status = db.Column(db.String(20), default='draft', nullable=False, index=True)
    planned_start_date = db.Column(db.Date, nullable=True)
    planned_end_date = db.Column(db.Date, nullable=True)
    actual_start_date = db.Column(db.Date, nullable=True)
    actual_end_date = db.Column(db.Date, nullable=True)
    cancel_reason = db.Column(db.String(500), nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    bom = db.relationship('BillOfMaterial', foreign_keys=[bom_id])
    branch = db.relationship('Branch', foreign_keys=[branch_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    materials = db.relationship('WorkOrderMaterial', backref='work_order', cascade='all, delete-orphan')
    operations = db.relationship('WorkOrderOperation', backref='work_order', cascade='all, delete-orphan',
                                 order_by='WorkOrderOperation.sequence_no')

    def __repr__(self):
        return f'<WorkOrder {self.wo_number} status={self.status}>'


class WorkOrderMaterial(db.Model):
    """Snapshot of a BillOfMaterialLine at release time (R-07 D2)."""
    __tablename__ = 'work_order_materials'

    id = db.Column(db.Integer, primary_key=True)
    wo_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    component_product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity_required = db.Column(db.Numeric(15, 4), nullable=False)
    quantity_issued = db.Column(db.Numeric(15, 4), default=0, nullable=False)
    uom_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)

    component_product = db.relationship('Product', foreign_keys=[component_product_id])
    uom = db.relationship('UnitOfMeasure', foreign_keys=[uom_id])

    def to_dict(self):
        return {
            'id': self.id,
            'component_product_id': self.component_product_id,
            'component_code': self.component_product.code if self.component_product else None,
            'component_name': self.component_product.name if self.component_product else None,
            'quantity_required': float(self.quantity_required),
            'quantity_issued': float(self.quantity_issued),
            'uom_code': self.uom.code if self.uom else None,
        }


class WorkOrderOperation(db.Model):
    """Snapshot of a BillOfMaterialOperation at release time (R-07 D2).
    Execution-tracking columns (status, actual timestamps, actual_minutes) were
    added by D3 (R-07 Discrete Track slice D3)."""
    __tablename__ = 'work_order_operations'

    id = db.Column(db.Integer, primary_key=True)
    wo_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False, index=True)
    sequence_no = db.Column(db.Integer, nullable=False)
    work_center_id = db.Column(db.Integer, db.ForeignKey('work_centers.id'), nullable=False)
    operation_name = db.Column(db.String(200), nullable=False)
    standard_time_minutes = db.Column(db.Numeric(10, 2), nullable=True)
    status = db.Column(db.String(20), default='pending', nullable=False)
    actual_start_at = db.Column(db.DateTime, nullable=True)
    actual_complete_at = db.Column(db.DateTime, nullable=True)
    actual_minutes = db.Column(db.Numeric(10, 2), nullable=True)

    work_center = db.relationship('WorkCenter', foreign_keys=[work_center_id])

    def to_dict(self):
        return {
            'id': self.id,
            'sequence_no': self.sequence_no,
            'work_center_id': self.work_center_id,
            'work_center_code': self.work_center.code if self.work_center else None,
            'operation_name': self.operation_name,
            'standard_time_minutes': (float(self.standard_time_minutes)
                                      if self.standard_time_minutes is not None else None),
            'status': self.status,
            'actual_start_at': self.actual_start_at.isoformat() if self.actual_start_at else None,
            'actual_complete_at': self.actual_complete_at.isoformat() if self.actual_complete_at else None,
            'actual_minutes': float(self.actual_minutes) if self.actual_minutes is not None else None,
        }
