"""Customer business style

Owner, 3 Nov 2026: Philgen's legacy sales invoice prints the buyer's business style
("Food Repacking and Distribution"); CAS had nowhere to keep it. One nullable text
column on the customer master, read by the SI pre-printed print. Existing customers
stay blank.

Revision ID: custbs_0001
Revises: bugrep_0001
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = 'custbs_0001'
down_revision = 'bugrep_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('business_style', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_column('business_style')
