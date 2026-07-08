"""add po_required to customers

Revision ID: a75a26b82c7f
Revises: b7780a041539
Create Date: 2026-07-08 18:07:26.080678

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a75a26b82c7f'
down_revision = 'b7780a041539'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('po_required', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.alter_column('po_required', server_default=None)


def downgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_column('po_required')
