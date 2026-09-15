"""add document_attachments table

Revision ID: docatt_0001
Revises: f179afe2918a
Create Date: 2026-09-15

Shared file attachments for Purchase Requisitions, Purchase Orders, Receiving
Reports and Cash Disbursement Vouchers. One polymorphic table keyed by
(document_type, document_id), the shape document_revisions already uses.

New table only -- no ALTER on an existing table, so no batch_alter_table needed.
document_id is a PLAIN Integer with no FK: it points at four different tables.
The users FK is NAMED so a later batch rebuild of this table can reproduce it.
"""
from alembic import op
import sqlalchemy as sa


revision = 'docatt_0001'
down_revision = 'f179afe2918a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'document_attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(length=40), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_filename', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'],
                                name='fk_document_attachments_uploaded_by'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stored_filename', name='uq_document_attachments_stored_filename'),
    )
    op.create_index('ix_document_attachments_doc', 'document_attachments',
                    ['document_type', 'document_id'])


def downgrade():
    op.drop_index('ix_document_attachments_doc', 'document_attachments')
    op.drop_table('document_attachments')
