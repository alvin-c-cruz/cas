from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

MOVEMENT_TYPES = ('receipt', 'issue', 'material_issue', 'production',
                  'purchase_return', 'sales_return', 'adjustment')


class StockMovement(db.Model):
    """Immutable, append-only stock ledger row. Never edited after insert; a
    correction is a new opposite movement. balance_*_after snapshot the running
    balance immediately after this movement (computed once, stored -- never
    replayed at read time)."""
    __tablename__ = 'stock_movements'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    movement_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Numeric(15, 4), nullable=False)          # signed: +in / -out
    unit_cost = db.Column(db.Numeric(15, 2), nullable=False)
    balance_qty_after = db.Column(db.Numeric(15, 4), nullable=False)
    balance_avg_cost_after = db.Column(db.Numeric(15, 2), nullable=False)
    balance_value_after = db.Column(db.Numeric(15, 2), nullable=False)
    source_document_type = db.Column(db.String(40), nullable=True)
    source_document_id = db.Column(db.Integer, nullable=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    product = db.relationship('Product')
    branch = db.relationship('Branch')
    journal_entry = db.relationship('JournalEntry')


class StockBalance(RowVersioned, db.Model):
    """Materialized current running balance, one row per (product, branch).
    RowVersioned guards the conditional-UPDATE-with-retry in service.post_movement."""
    __tablename__ = 'stock_balances'
    __table_args__ = (db.UniqueConstraint('product_id', 'branch_id', name='uq_stock_balance_product_branch'),)

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    quantity_on_hand = db.Column(db.Numeric(15, 4), nullable=False, default=0)
    average_unit_cost = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    total_value = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    product = db.relationship('Product')
    branch = db.relationship('Branch')


class StockCostLayer(db.Model):
    """One open-or-exhausted FIFO cost layer (R-03 slice 2b). Created either by
    a real receipt (source_movement_id set) or by the one-time cutover
    bootstrap for a product's first FIFO movement (source_movement_id null).
    Never deleted, even at remaining_qty=0 -- append-only history, same
    philosophy as StockMovement. remaining_qty MAY go negative (a layer-
    exhaustion deficit -- see fifo.py); it is never a simple "qty left"
    display value in isolation without checking sign."""
    __tablename__ = 'stock_cost_layers'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    original_qty = db.Column(db.Numeric(15, 4), nullable=False)
    remaining_qty = db.Column(db.Numeric(15, 4), nullable=False)
    unit_cost = db.Column(db.Numeric(15, 2), nullable=False)
    received_at = db.Column(db.DateTime, nullable=False)
    source_movement_id = db.Column(db.Integer, db.ForeignKey('stock_movements.id'), nullable=True)

    product = db.relationship('Product')
    branch = db.relationship('Branch')
    source_movement = db.relationship('StockMovement')


class StockLayerConsumption(db.Model):
    """One (OUT movement, layer) draw record (R-03 slice 2b) -- what makes a
    FIFO issue-reversal exact (restore precisely these layers by precisely
    these amounts) instead of approximate. One movement can produce several
    of these rows if it spanned multiple layers."""
    __tablename__ = 'stock_layer_consumptions'

    id = db.Column(db.Integer, primary_key=True)
    movement_id = db.Column(db.Integer, db.ForeignKey('stock_movements.id'), nullable=False, index=True)
    layer_id = db.Column(db.Integer, db.ForeignKey('stock_cost_layers.id'), nullable=False, index=True)
    qty_consumed = db.Column(db.Numeric(15, 4), nullable=False)
    unit_cost_at_consumption = db.Column(db.Numeric(15, 2), nullable=False)

    movement = db.relationship('StockMovement')
    layer = db.relationship('StockCostLayer')


class StockLot(db.Model):
    """One received-or-exhausted specific-identification lot (R-03 slice 2d).
    Created either by a real receipt (source_movement_id set) or by an
    "opening" Stock Adjustment establishing a pre-existing batch (also
    source_movement_id set -- there is no separate bootstrap mechanism the
    way FIFO has one; the user names their existing batches explicitly via
    an opening receipt, which fits specific-ID's whole point better than an
    auto-generated, unlabeled opening lot would). Never deleted, even at
    remaining_qty=0 -- append-only history, same philosophy as
    StockMovement/StockCostLayer. Unlike a FIFO layer, remaining_qty can
    NEVER go negative -- a specific-ID issue that would exceed a lot's
    remaining quantity is rejected before posting (see lots.py)."""
    __tablename__ = 'stock_lots'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    original_qty = db.Column(db.Numeric(15, 4), nullable=False)
    remaining_qty = db.Column(db.Numeric(15, 4), nullable=False)
    unit_cost = db.Column(db.Numeric(15, 2), nullable=False)
    received_at = db.Column(db.DateTime, nullable=False)
    lot_reference = db.Column(db.String(200), nullable=True)
    source_movement_id = db.Column(db.Integer, db.ForeignKey('stock_movements.id'), nullable=True)

    product = db.relationship('Product')
    branch = db.relationship('Branch')
    source_movement = db.relationship('StockMovement')


class StockLotConsumption(db.Model):
    """One (OUT movement, lot) draw record (R-03 slice 2d) -- what makes a
    specific-ID issue-reversal exact. Unlike StockLayerConsumption, a
    specific-ID movement produces AT MOST ONE of these rows, never several
    -- a line always draws from exactly one user-picked lot, no
    auto-splitting across lots."""
    __tablename__ = 'stock_lot_consumptions'

    id = db.Column(db.Integer, primary_key=True)
    movement_id = db.Column(db.Integer, db.ForeignKey('stock_movements.id'), nullable=False, index=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('stock_lots.id'), nullable=False, index=True)
    qty_consumed = db.Column(db.Numeric(15, 4), nullable=False)
    unit_cost_at_consumption = db.Column(db.Numeric(15, 2), nullable=False)

    movement = db.relationship('StockMovement')
    lot = db.relationship('StockLot')


REASON_TYPES = ('correction', 'opening', 'physical_count')


class StockAdjustment(RowVersioned, db.Model):
    __tablename__ = 'stock_adjustments'

    id = db.Column(db.Integer, primary_key=True)
    sa_number = db.Column(db.String(50), unique=True, index=True, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    adjustment_date = db.Column(db.Date, nullable=False)
    reason_type = db.Column(db.String(20), nullable=False, default='correction', server_default='correction')
    notes = db.Column(db.Text, nullable=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    branch = db.relationship('Branch')
    journal_entry = db.relationship('JournalEntry')
    posted_by = db.relationship('User', foreign_keys=[posted_by_id])
    lines = db.relationship('StockAdjustmentLine', backref='adjustment',
                            cascade='all, delete-orphan', order_by='StockAdjustmentLine.id')


class StockAdjustmentLine(db.Model):
    __tablename__ = 'stock_adjustment_lines'

    id = db.Column(db.Integer, primary_key=True)
    adjustment_id = db.Column(db.Integer, db.ForeignKey('stock_adjustments.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity_delta = db.Column(db.Numeric(15, 4), nullable=False)   # signed
    unit_cost = db.Column(db.Numeric(15, 2), nullable=True)         # required only for positive lines
    lot_id = db.Column(db.Integer, db.ForeignKey('stock_lots.id'), nullable=True)     # negative specific-ID lines only
    lot_reference = db.Column(db.String(200), nullable=True)         # positive specific-ID lines only, optional
    note = db.Column(db.String(500), nullable=True)

    product = db.relationship('Product')
    lot = db.relationship('StockLot')


class PhysicalCount(RowVersioned, db.Model):
    """A full physical count session for one branch: snapshots book quantity
    for every tracked product, records what was counted, and (on approve)
    auto-posts a StockAdjustment for eligible variances. RowVersioned because
    a draft count's line grid can be saved incrementally across more than one
    sitting -- counting a real warehouse isn't a single form submit."""
    __tablename__ = 'physical_counts'

    id = db.Column(db.Integer, primary_key=True)
    pc_number = db.Column(db.String(50), unique=True, index=True, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    count_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft')
    notes = db.Column(db.Text, nullable=True)
    stock_adjustment_id = db.Column(db.Integer, db.ForeignKey('stock_adjustments.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    branch = db.relationship('Branch')
    stock_adjustment = db.relationship('StockAdjustment')
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    lines = db.relationship('PhysicalCountLine', backref='count',
                            cascade='all, delete-orphan', order_by='PhysicalCountLine.id')


class PhysicalCountLine(db.Model):
    __tablename__ = 'physical_count_lines'

    id = db.Column(db.Integer, primary_key=True)
    count_id = db.Column(db.Integer, db.ForeignKey('physical_counts.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    book_qty_snapshot = db.Column(db.Numeric(15, 4), nullable=False)
    counted_qty = db.Column(db.Numeric(15, 4), nullable=True)
    note = db.Column(db.String(500), nullable=True)

    product = db.relationship('Product')
