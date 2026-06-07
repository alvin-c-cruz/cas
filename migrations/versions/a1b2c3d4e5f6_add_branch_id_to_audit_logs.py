"""add branch_id to audit_logs

Revision ID: a1b2c3d4e5f6
Revises: 687639bc8eb0
Create Date: 2026-06-07 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '687639bc8eb0'
branch_labels = None
depends_on = None


def upgrade():
    # Add branch_id column (nullable - not all audit logs have branch context)
    with op.batch_alter_table('audit_logs') as batch_op:
        batch_op.add_column(
            sa.Column('branch_id', sa.Integer(), nullable=True)
        )
        batch_op.create_index('ix_audit_logs_branch_id', ['branch_id'], unique=False)
        batch_op.create_foreign_key('fk_audit_logs_branch', 'branches', ['branch_id'], ['id'])


def downgrade():
    # Remove foreign key, index, and column
    with op.batch_alter_table('audit_logs') as batch_op:
        batch_op.drop_constraint('fk_audit_logs_branch', type_='foreignkey')
        batch_op.drop_index('ix_audit_logs_branch_id')
        batch_op.drop_column('branch_id')
