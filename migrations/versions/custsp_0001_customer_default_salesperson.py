"""Customer default salesperson

Revision ID: custsp_0001
Revises: wod4_0001
Create Date: 2026-07-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'custsp_0001'
down_revision = 'wod4_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_salesperson_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_column('default_salesperson_id')
