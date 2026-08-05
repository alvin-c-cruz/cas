"""Sales Order revisions -- an append-only record of post-confirm amendments.

Rev 0 is the order as originally confirmed; Rev N is the order after the Nth
amendment. The live `sales_orders` row always equals the highest revision's
snapshot, so Rev 0's snapshot reproduces the job order slip production holds.

Rows are never updated or deleted, so this model deliberately does NOT extend
RowVersioned -- there is no lost-update to guard against.
"""
from app import db
from app.utils import ph_now


class SalesOrderRevision(db.Model):
    __tablename__ = 'sales_order_revisions'
    __table_args__ = (
        db.UniqueConstraint('sales_order_id', 'revision_number',
                            name='uq_so_revision_number'),
    )

    id = db.Column(db.Integer, primary_key=True)

    sales_order_id = db.Column(db.Integer, db.ForeignKey('sales_orders.id'),
                               nullable=False, index=True)

    # 0-based. Rev 0 == the order as originally confirmed.
    revision_number = db.Column(db.Integer, nullable=False)

    # Complete order state -- header + all lines -- AS OF this revision.
    snapshot_json = db.Column(db.Text, nullable=False)

    # Required (>=10 chars) for N >= 1; null on Rev 0.
    reason = db.Column(db.String(500), nullable=True)

    authorizing_po_number = db.Column(db.String(100), nullable=True)

    amended_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    amended_by = db.relationship('User', foreign_keys=[amended_by_id])
    amended_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'),
                          nullable=True, index=True)

    def __repr__(self):
        return f'<SalesOrderRevision so={self.sales_order_id} rev={self.revision_number}>'
