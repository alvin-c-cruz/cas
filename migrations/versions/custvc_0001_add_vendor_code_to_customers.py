"""add vendor_code to customers

Revision ID: custvc_0001
Revises: drdata_0001
Create Date: 2026-07-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'custvc_0001'
down_revision = 'drdata_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vendor_code', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_column('vendor_code')
