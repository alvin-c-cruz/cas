"""approved_email status + requested_by + nullable approved_by

Revision ID: 78bed40214ed
Revises: 6fec6b362f43
Create Date: 2026-06-26 20:30:15.517955

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '78bed40214ed'
down_revision = '6fec6b362f43'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('approved_emails', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=False, server_default='approved'))
        batch_op.add_column(sa.Column('requested_by_user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(), nullable=True))
        batch_op.alter_column('approved_by_user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.create_foreign_key(
            'fk_approved_emails_requested_by_user_id',
            'users', ['requested_by_user_id'], ['id']
        )

    op.execute("UPDATE approved_emails SET status='approved' WHERE status IS NULL")


def downgrade():
    with op.batch_alter_table('approved_emails', schema=None) as batch_op:
        batch_op.drop_constraint('fk_approved_emails_requested_by_user_id', type_='foreignkey')
        batch_op.alter_column('approved_by_user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('requested_by_user_id')
        batch_op.drop_column('status')
