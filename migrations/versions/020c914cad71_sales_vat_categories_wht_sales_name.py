"""sales vat categories + wht sales_name

Revision ID: 020c914cad71
Revises: ff59aff7c151
Create Date: 2026-06-20 08:27:13.748881

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '020c914cad71'
down_revision = 'ff59aff7c151'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sales_vat_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('transaction_nature', sa.String(length=30), nullable=False),
    sa.Column('output_vat_account_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('updated_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['output_vat_account_id'], ['accounts.id'], ),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('sales_vat_category_change_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('sales_vat_category_id', sa.Integer(), nullable=True),
    sa.Column('proposed_data', sa.Text(), nullable=True),
    sa.Column('requested_by_id', sa.Integer(), nullable=False),
    sa.Column('requested_at', sa.DateTime(), nullable=False),
    sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('review_notes', sa.Text(), nullable=True),
    sa.Column('request_reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sales_vat_category_id'], ['sales_vat_categories.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('withholding_tax', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sales_name', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('withholding_tax', schema=None) as batch_op:
        batch_op.drop_column('sales_name')

    op.drop_table('sales_vat_category_change_requests')
    op.drop_table('sales_vat_categories')
