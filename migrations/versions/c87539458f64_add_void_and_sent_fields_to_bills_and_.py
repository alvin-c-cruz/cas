"""Add void and sent fields to bills and invoices

Revision ID: c87539458f64
Revises: 7e10975008c2
Create Date: 2026-06-09 21:04:05.643601

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c87539458f64'
down_revision = '7e10975008c2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.add_column(sa.Column('voided_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('voided_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('void_reason', sa.String(length=255), nullable=True))
        batch_op.create_foreign_key('fk_purchase_bills_voided_by', 'users', ['voided_by_id'], ['id'])

    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sent_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('sent_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('voided_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('voided_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('void_reason', sa.String(length=255), nullable=True))
        batch_op.create_foreign_key('fk_sales_invoices_sent_by', 'users', ['sent_by_id'], ['id'])
        batch_op.create_foreign_key('fk_sales_invoices_voided_by', 'users', ['voided_by_id'], ['id'])


def downgrade():
    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.drop_constraint('fk_sales_invoices_voided_by', type_='foreignkey')
        batch_op.drop_constraint('fk_sales_invoices_sent_by', type_='foreignkey')
        batch_op.drop_column('void_reason')
        batch_op.drop_column('voided_by_id')
        batch_op.drop_column('voided_at')
        batch_op.drop_column('sent_by_id')
        batch_op.drop_column('sent_at')

    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.drop_constraint('fk_purchase_bills_voided_by', type_='foreignkey')
        batch_op.drop_column('void_reason')
        batch_op.drop_column('voided_by_id')
        batch_op.drop_column('voided_at')
