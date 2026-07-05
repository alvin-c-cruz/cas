"""add backup_runs table

Revision ID: ad8a4fdb9f89
Revises: 307cc71c8779
Create Date: 2026-07-05 11:21:41.961772

Hand-written: only creates the new backup_runs table. Alembic autogen also
surfaced pre-existing model-vs-DB index/table drift (receipts, accounts_payable,
print_layouts) that is UNRELATED to this change and was deliberately excluded.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ad8a4fdb9f89'
down_revision = '307cc71c8779'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'backup_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('triggered_by', sa.String(length=16), nullable=False),
        sa.Column('actor', sa.String(length=80), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('db_plaintext_sha256', sa.String(length=64), nullable=True),
        sa.Column('db_size', sa.Integer(), nullable=True),
        sa.Column('artifacts', sa.Text(), nullable=True),
        sa.Column('manifest_sha256', sa.String(length=64), nullable=True),
        sa.Column('key_id', sa.String(length=16), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('backup_runs')
