"""receiving_report_items.stock_movement_id (R-03 slice 2a-ii)

Revision ID: rritemsm_0001
Revises: stkadj_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'rritemsm_0001'
down_revision = 'stkadj_0001'   # confirm this matches the LIVE head before committing
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('receiving_report_items') as batch_op:
        # Plain Integer, no inline ForeignKey -- batch add_column cannot carry one
        # (SQLite FK enforcement is off app-wide anyway; the ORM side still
        # declares db.ForeignKey for the relationship).
        batch_op.add_column(sa.Column('stock_movement_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('receiving_report_items') as batch_op:
        batch_op.drop_column('stock_movement_id')
