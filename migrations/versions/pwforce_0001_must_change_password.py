"""Force a password change after someone else set it (users.must_change_password)

Work order 2026-11-10-force-password-change-after-admin-reset (owner, 10 Nov 2026: "Both"; 12 Nov 2026:
"PW-3 A"). Set by an admin's reset of another user's password and by `flask reset-password`; cleared by
the user's own change. Every existing user starts at 0 (false), so nobody is forced by the upgrade.

Revision ID: pwforce_0001
Revises: chqpay_0001
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = 'pwforce_0001'
down_revision = 'chqpay_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), nullable=False,
                                      server_default='0'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('must_change_password')
