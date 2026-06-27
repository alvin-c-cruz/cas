"""add book_permissions to approved_emails

Revision ID: 104d8f7b4cb0
Revises: 36517765f386
Create Date: 2026-06-27 12:44:50.853042

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '104d8f7b4cb0'
down_revision = '36517765f386'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('approved_emails', schema=None) as batch_op:
        batch_op.add_column(sa.Column('book_permissions', sa.Text(), nullable=True,
                                      server_default='{}'))


def downgrade():
    with op.batch_alter_table('approved_emails', schema=None) as batch_op:
        batch_op.drop_column('book_permissions')
