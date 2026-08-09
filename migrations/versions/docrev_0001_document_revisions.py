"""add document_revisions table

Revision ID: docrev_0001
Revises: sorev_0002
Create Date: 2026-08-09

Shared append-only revision log for post-approval amendment. One row per
revision holding a full JSON snapshot of the document as of that revision.

New table only -- no ALTER on an existing table, so no batch_alter_table needed.
document_id is a PLAIN Integer with no FK: it points at eight different tables.
"""
from alembic import op
import sqlalchemy as sa


revision = 'docrev_0001'
down_revision = 'sorev_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'document_revisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(length=40), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('revision_number', sa.Integer(), nullable=False),
        sa.Column('snapshot_json', sa.Text(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('authorizing_reference', sa.String(length=100), nullable=True),
        sa.Column('amended_by_id', sa.Integer(), nullable=True),
        sa.Column('amended_at', sa.DateTime(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['amended_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_type', 'document_id', 'revision_number',
                            name='uq_document_revision_number'),
    )
    op.create_index('ix_document_revisions_doc', 'document_revisions',
                    ['document_type', 'document_id'])
    op.create_index('ix_document_revisions_branch_id', 'document_revisions', ['branch_id'])


def downgrade():
    op.drop_index('ix_document_revisions_branch_id', 'document_revisions')
    op.drop_index('ix_document_revisions_doc', 'document_revisions')
    op.drop_table('document_revisions')
