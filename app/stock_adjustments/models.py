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
