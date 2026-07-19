"""add work orders table

Revision ID: 1f53183bf080
Revises: 47507deefc6f
Create Date: 2026-07-19 11:19:14.436996

R-07 Discrete Track slice D2: WorkOrder header + its two snapshot child
tables (WorkOrderMaterial, WorkOrderOperation). All three land in one
migration -- WorkOrder's own SQLAlchemy relationships reference the other
two by name, so they can't be split across separate migrations/tasks
without breaking mapper configuration on the very first DB touch.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f53183bf080'
down_revision = '47507deefc6f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('work_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('wo_number', sa.String(length=50), nullable=False),
        sa.Column('bom_id', sa.Integer(), sa.ForeignKey('bills_of_material.id'), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('qty_to_produce', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('planned_start_date', sa.Date(), nullable=True),
        sa.Column('planned_end_date', sa.Date(), nullable=True),
        sa.Column('actual_start_date', sa.Date(), nullable=True),
        sa.Column('actual_end_date', sa.Date(), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('wo_number', name='uq_work_orders_wo_number'),
    )
    with op.batch_alter_table('work_orders', schema=None) as b:
        b.create_index('ix_work_orders_branch_id', ['branch_id'])
        b.create_index('ix_work_orders_status', ['status'])
        b.create_index('ix_work_orders_wo_number', ['wo_number'])

    op.create_table('work_order_materials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('wo_id', sa.Integer(), sa.ForeignKey('work_orders.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('component_product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity_required', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('quantity_issued', sa.Numeric(precision=15, scale=4), nullable=False, server_default='0'),
        sa.Column('uom_id', sa.Integer(), sa.ForeignKey('units_of_measure.id'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('work_order_materials', schema=None) as b:
        b.create_index('ix_work_order_materials_wo_id', ['wo_id'])

    op.create_table('work_order_operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('wo_id', sa.Integer(), sa.ForeignKey('work_orders.id'), nullable=False),
        sa.Column('sequence_no', sa.Integer(), nullable=False),
        sa.Column('work_center_id', sa.Integer(), sa.ForeignKey('work_centers.id'), nullable=False),
        sa.Column('operation_name', sa.String(length=200), nullable=False),
        sa.Column('standard_time_minutes', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('work_order_operations', schema=None) as b:
        b.create_index('ix_work_order_operations_wo_id', ['wo_id'])


def downgrade():
    with op.batch_alter_table('work_order_operations', schema=None) as b:
        b.drop_index('ix_work_order_operations_wo_id')
    op.drop_table('work_order_operations')
    with op.batch_alter_table('work_order_materials', schema=None) as b:
        b.drop_index('ix_work_order_materials_wo_id')
    op.drop_table('work_order_materials')
    with op.batch_alter_table('work_orders', schema=None) as b:
        b.drop_index('ix_work_orders_wo_number')
        b.drop_index('ix_work_orders_status')
        b.drop_index('ix_work_orders_branch_id')
    op.drop_table('work_orders')
