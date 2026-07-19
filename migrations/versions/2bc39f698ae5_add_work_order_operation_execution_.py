"""add work order operation execution tracking

Revision ID: 2bc39f698ae5
Revises: 1f53183bf080
Create Date: 2026-07-19 15:07:55.392106

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2bc39f698ae5'
down_revision = '1f53183bf080'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('work_order_operations', schema=None) as b:
        b.add_column(sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'))
        b.add_column(sa.Column('actual_start_at', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('actual_complete_at', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('actual_minutes', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade():
    with op.batch_alter_table('work_order_operations', schema=None) as b:
        b.drop_column('actual_minutes')
        b.drop_column('actual_complete_at')
        b.drop_column('actual_start_at')
        b.drop_column('status')
