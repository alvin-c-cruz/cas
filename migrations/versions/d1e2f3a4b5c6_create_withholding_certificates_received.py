"""create withholding_certificates_received table

Revision ID: d1e2f3a4b5c6
Revises: e5f6a7b8c9d0
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'withholding_certificates_received',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('certificate_number', sa.String(length=50), nullable=False),
        sa.Column('date_received', sa.Date(), nullable=False),
        sa.Column('period_from', sa.Date(), nullable=False),
        sa.Column('period_to', sa.Date(), nullable=False),
        sa.Column('wt_id', sa.Integer(), nullable=False),
        sa.Column('income_payment', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('tax_withheld', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('attachment_path', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(length=80), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id']),
        sa.ForeignKeyConstraint(['wt_id'], ['withholding_tax.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('withholding_certificates_received', schema=None) as batch_op:
        batch_op.create_index('ix_withholding_certificates_received_branch_id',
                              ['branch_id'], unique=False)
        batch_op.create_index('ix_withholding_certificates_received_customer_id',
                              ['customer_id'], unique=False)
        batch_op.create_index('ix_withholding_certificates_received_wt_id',
                              ['wt_id'], unique=False)


def downgrade():
    with op.batch_alter_table('withholding_certificates_received', schema=None) as batch_op:
        batch_op.drop_index('ix_withholding_certificates_received_wt_id')
        batch_op.drop_index('ix_withholding_certificates_received_customer_id')
        batch_op.drop_index('ix_withholding_certificates_received_branch_id')
    op.drop_table('withholding_certificates_received')
