"""make purchase_bills.notes required

Revision ID: 4412b44eb668
Revises: dfc2126c99a8
Create Date: 2026-06-13 20:18:56.788601

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4412b44eb668'
down_revision = 'dfc2126c99a8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE purchase_bills SET notes = '(No particulars recorded)' WHERE notes IS NULL OR notes = ''")
    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.alter_column('notes', existing_type=sa.Text(), nullable=False)


def downgrade():
    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.alter_column('notes', existing_type=sa.Text(), nullable=True)
