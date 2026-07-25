"""add customer_delivery_sites

Revision ID: cds_0001
Revises: custsp_0001
Create Date: 2026-07-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cds_0001'
down_revision = 'custsp_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_delivery_sites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table('customer_delivery_sites', schema=None) as b:
        b.create_index('ix_customer_delivery_sites_customer_id', ['customer_id'])


def downgrade():
    op.drop_table('customer_delivery_sites')
