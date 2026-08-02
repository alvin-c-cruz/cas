"""Production Run -- the process-track costing document header (R-07 Process Track
slice P2). Period-based rather than job-based: a run accumulates cost at a
ManufacturingDepartment over period_start..period_end, and is costed by the
weighted-average equivalent-units method in P3/P4.

On open it snapshots its BillOfMaterial's component lines onto ProductionRunMaterial
so a later BOM edit never disturbs a run already under way -- the same rule Wave 0
set for the Discrete track's WorkOrder.

Deliberately carries NO product_id. BillOfMaterial is strictly 1:1 with Product
(Wave 0), so the output product is derived through `bom.product`; storing it would
be a second source of truth that can drift. Owner decision 2026-08-02, a knowing
divergence from the arc spec's field list.

See docs/superpowers/specs/2026-07-19-manufacturing-r07-design.md, Process Track.
"""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

RUN_STATUSES = ('open', 'closed', 'cancelled')


class ProductionRun(RowVersioned, db.Model):
    __tablename__ = 'production_runs'

    id = db.Column(db.Integer, primary_key=True)
    run_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    bom_id = db.Column(db.Integer, db.ForeignKey('bills_of_material.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('manufacturing_departments.id'),
                              nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='open', nullable=False, index=True)

    # Unit counters. units_started drives P2's material snapshot; the other three are
    # the equivalent-units inputs P3/P4 consume, landed in this migration by owner
    # decision so a later slice needs no second ALTER on live client databases.
    units_started = db.Column(db.Numeric(15, 4), default=0, nullable=False)
    units_completed_and_transferred = db.Column(db.Numeric(15, 4), default=0, nullable=False)
    units_ending_wip = db.Column(db.Numeric(15, 4), default=0, nullable=False)
    ending_wip_pct_complete = db.Column(db.Numeric(5, 2), nullable=True)
    # Conversion cost (labour + overhead) for the period, entered MANUALLY
    # (owner decision 2026-08-02). The arc spec's "reuse ExpenseAllocationRule"
    # is impossible -- that driver is product-line scoped with no department or
    # period dimension; see the spec's dated correction.
    conversion_cost = db.Column(db.Numeric(15, 2), nullable=True)

    # --- Period close + WIP carry-forward (R-07 P4) ---
    # Beginning WIP is what the PREDECESSOR run left in WIP, pulled forward when this
    # run is created (not pushed at close -- at close time the successor usually does
    # not exist yet, because the old period is closed before the new one is opened).
    # NOT NULL with a 0 default on purpose: every run has a beginning WIP even when it
    # is zero, and a NULL would silently drop out of the cost pool's arithmetic rather
    # than adding nothing.
    beginning_wip_units = db.Column(db.Numeric(15, 4), default=0, nullable=False,
                                    server_default='0')
    beginning_wip_cost = db.Column(db.Numeric(15, 2), default=0, nullable=False,
                                   server_default='0')
    # Frozen AT CLOSE, never recomputed -- mirrors WorkOrder.actual_unit_cost. A later
    # Product.standard_cost or BOM edit must not be able to retroactively disagree with
    # what was actually posted. ending_wip_cost is the residual PLUG (cost pool minus
    # the amount transferred out), NOT units x cost/EU: the ending-WIP units are only
    # partially complete, so valuing them at a full equivalent-unit cost would strand
    # the difference in WIP permanently. Carrying the plug is what keeps WIP tied to
    # the GL, and it becomes the successor run's beginning_wip_cost.
    ending_wip_cost = db.Column(db.Numeric(15, 2), nullable=True)
    transferred_unit_cost = db.Column(db.Numeric(15, 2), nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    # Plain Integer, not db.ForeignKey: a batch add_column cannot carry an inline FK
    # ("Constraint must have a name") and SQLite FK enforcement is off app-wide anyway.
    closed_by_id = db.Column(db.Integer, nullable=True)

    cancel_reason = db.Column(db.String(500), nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    bom = db.relationship('BillOfMaterial')
    department = db.relationship('ManufacturingDepartment')
    branch = db.relationship('Branch')
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    materials = db.relationship('ProductionRunMaterial', backref='run',
                                cascade='all, delete-orphan', order_by='ProductionRunMaterial.line_number')

    @property
    def output_product(self):
        """Derived, never stored -- BOM is 1:1 with Product."""
        return self.bom.product if self.bom else None

    def __repr__(self):
        return f'<ProductionRun {self.run_number} [{self.status}]>'

    def to_dict(self):
        product = self.output_product
        return {
            'id': self.id, 'run_number': self.run_number, 'bom_id': self.bom_id,
            'department_id': self.department_id, 'branch_id': self.branch_id,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'status': self.status,
            'units_started': float(self.units_started or 0),
            'units_completed_and_transferred': float(self.units_completed_and_transferred or 0),
            'units_ending_wip': float(self.units_ending_wip or 0),
            'ending_wip_pct_complete': (float(self.ending_wip_pct_complete)
                                        if self.ending_wip_pct_complete is not None else None),
            'conversion_cost': (float(self.conversion_cost)
                                if self.conversion_cost is not None else None),
            'beginning_wip_units': float(self.beginning_wip_units or 0),
            'beginning_wip_cost': float(self.beginning_wip_cost or 0),
            'ending_wip_cost': (float(self.ending_wip_cost)
                                if self.ending_wip_cost is not None else None),
            'transferred_unit_cost': (float(self.transferred_unit_cost)
                                      if self.transferred_unit_cost is not None else None),
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'closed_by_id': self.closed_by_id,
            'output_product_code': product.code if product else None,
        }


class ProductionRunMaterial(db.Model):
    """Snapshot of a BillOfMaterialLine at run-open time (R-07 P2), mirroring
    WorkOrderMaterial."""
    __tablename__ = 'production_run_materials'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('production_runs.id'), nullable=False, index=True)
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
            'quantity_issued': float(self.quantity_issued or 0),
        }
