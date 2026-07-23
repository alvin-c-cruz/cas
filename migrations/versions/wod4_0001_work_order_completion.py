"""R-07 D4: Work Order completion columns + work_order_completions table

Revision ID: wod4_0001
Revises: physcount_0001
Create Date: 2026-07-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'wod4_0001'
down_revision = 'physcount_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('work_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('qty_completed_to_date', sa.Numeric(15, 4),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('actual_unit_cost', sa.Numeric(15, 2), nullable=True))
        batch_op.add_column(sa.Column('force_closed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('force_close_note', sa.Text(), nullable=True))

    op.create_table(
        'work_order_completions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('work_order_id', sa.Integer(), sa.ForeignKey('work_orders.id'), nullable=False),
        sa.Column('qty_completed', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(15, 2), nullable=False),
        sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('completed_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table('work_order_completions', schema=None) as batch_op:
        batch_op.create_index('ix_work_order_completions_work_order_id', ['work_order_id'], unique=False)


def downgrade():
    op.drop_table('work_order_completions')
    with op.batch_alter_table('work_orders', schema=None) as batch_op:
        batch_op.drop_column('force_close_note')
        batch_op.drop_column('force_closed_at')
        batch_op.drop_column('actual_unit_cost')
        batch_op.drop_column('qty_completed_to_date')
