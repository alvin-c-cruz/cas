"""add bill of material operations table

Revision ID: b10009747c18
Revises: fa3ca2bc569d
Create Date: 2026-07-19 10:15:53.776800

R-07 Discrete Track slice D1: routing steps for discrete-mode BOMs.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b10009747c18'
down_revision = 'fa3ca2bc569d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bill_of_material_operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bom_id', sa.Integer(), sa.ForeignKey('bills_of_material.id'), nullable=False),
        sa.Column('sequence_no', sa.Integer(), nullable=False),
        sa.Column('work_center_id', sa.Integer(), sa.ForeignKey('work_centers.id'), nullable=False),
        sa.Column('operation_name', sa.String(length=200), nullable=False),
        sa.Column('standard_time_minutes', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('bill_of_material_operations', schema=None) as b:
        b.create_index('ix_bill_of_material_operations_bom_id', ['bom_id'])


def downgrade():
    with op.batch_alter_table('bill_of_material_operations', schema=None) as b:
        b.drop_index('ix_bill_of_material_operations_bom_id')
    op.drop_table('bill_of_material_operations')
