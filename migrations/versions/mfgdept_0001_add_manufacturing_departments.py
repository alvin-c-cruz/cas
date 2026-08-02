"""add manufacturing_departments table

Revision ID: mfgdept_0001
Revises: custvc_0001
Create Date: 2026-08-02

R-07 Process Track slice P1: ManufacturingDepartment master data -- process mode's
cost-pool counterpart to WorkCenter. A brand-new table, so a plain create_table is
correct here; batch_alter_table is only needed for ALTER under SQLite.

Purely additive: no existing table is touched and no data is migrated, so this is
safe on every deployed client. The module itself ships default-off.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'mfgdept_0001'
down_revision = 'custvc_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'manufacturing_departments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('manufacturing_departments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_manufacturing_departments_branch_id'),
                              ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_manufacturing_departments_code'),
                              ['code'], unique=False)


def downgrade():
    with op.batch_alter_table('manufacturing_departments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_manufacturing_departments_code'))
        batch_op.drop_index(batch_op.f('ix_manufacturing_departments_branch_id'))
    op.drop_table('manufacturing_departments')
