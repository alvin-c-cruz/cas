"""add is_salesperson to employees

Revision ID: b7780a041539
Revises: e95cdff4e8e6
Create Date: 2026-07-08 17:09:49.220852

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7780a041539'
down_revision = 'e95cdff4e8e6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_salesperson', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.alter_column('is_salesperson', server_default=None)


def downgrade():
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_column('is_salesperson')
