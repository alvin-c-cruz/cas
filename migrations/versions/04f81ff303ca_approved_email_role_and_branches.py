"""approved_email role and branches

Revision ID: 04f81ff303ca
Revises: c6aaf3c5c0fa
Create Date: 2026-06-27 06:01:51.472830

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '04f81ff303ca'
down_revision = 'c6aaf3c5c0fa'
branch_labels = None
depends_on = None


def upgrade():
    # Delegated-registration role on the approved email (nullable; legacy rows stay None).
    with op.batch_alter_table('approved_emails', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=20), nullable=True))

    # Branch(es) the registrant is assigned to (mirrors user_branches).
    op.create_table(
        'approved_email_branches',
        sa.Column('approved_email_id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['approved_email_id'], ['approved_emails.id']),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.PrimaryKeyConstraint('approved_email_id', 'branch_id'),
    )


def downgrade():
    op.drop_table('approved_email_branches')
    with op.batch_alter_table('approved_emails', schema=None) as batch_op:
        batch_op.drop_column('role')
