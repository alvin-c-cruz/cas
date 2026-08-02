"""add production_runs and production_run_materials tables

Revision ID: prodrun_0001
Revises: mfgdept_0001
Create Date: 2026-08-02

R-07 Process Track slice P2. Both tables land in ONE migration: ProductionRun's
SQLAlchemy relationship references ProductionRunMaterial by name, so splitting
them breaks mapper configuration on the very first DB touch -- the same reason
the D2 work_orders migration bundled its three tables.

All of P3/P4's equivalent-units columns (units_completed_and_transferred,
units_ending_wip, ending_wip_pct_complete) are created here by owner decision
(2026-08-02) rather than by a later ALTER, so no follow-up slice has to migrate
5 live client databases again.

Purely additive: no existing table is touched, no data migrated. The module
ships default-off.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'prodrun_0001'
down_revision = 'mfgdept_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'production_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_number', sa.String(length=50), nullable=False),
        sa.Column('bom_id', sa.Integer(), sa.ForeignKey('bills_of_material.id'), nullable=False),
        sa.Column('department_id', sa.Integer(),
                  sa.ForeignKey('manufacturing_departments.id'), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
        sa.Column('units_started', sa.Numeric(precision=15, scale=4),
                  nullable=False, server_default='0'),
        sa.Column('units_completed_and_transferred', sa.Numeric(precision=15, scale=4),
                  nullable=False, server_default='0'),
        sa.Column('units_ending_wip', sa.Numeric(precision=15, scale=4),
                  nullable=False, server_default='0'),
        sa.Column('ending_wip_pct_complete', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_number', name='uq_production_runs_run_number'),
    )
    with op.batch_alter_table('production_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_production_runs_run_number'),
                              ['run_number'], unique=False)
        batch_op.create_index(batch_op.f('ix_production_runs_department_id'),
                              ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_production_runs_branch_id'),
                              ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_production_runs_status'), ['status'], unique=False)

    op.create_table(
        'production_run_materials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('production_runs.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('component_product_id', sa.Integer(),
                  sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity_required', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('quantity_issued', sa.Numeric(precision=15, scale=4),
                  nullable=False, server_default='0'),
        sa.Column('uom_id', sa.Integer(), sa.ForeignKey('units_of_measure.id'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('production_run_materials', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_production_run_materials_run_id'),
                              ['run_id'], unique=False)


def downgrade():
    with op.batch_alter_table('production_run_materials', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_production_run_materials_run_id'))
    op.drop_table('production_run_materials')
    with op.batch_alter_table('production_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_production_runs_status'))
        batch_op.drop_index(batch_op.f('ix_production_runs_branch_id'))
        batch_op.drop_index(batch_op.f('ix_production_runs_department_id'))
        batch_op.drop_index(batch_op.f('ix_production_runs_run_number'))
    op.drop_table('production_runs')
