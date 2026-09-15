"""required/labeled attachments: kind column + approved_incomplete_slots marker

Revision ID: reqatt_0001
Revises: docatt_0001
Create Date: 2026-09-15

Adds, for the required/labeled attachments feature (see
docs/design/2026-09-15-required-labeled-attachments-spec.md):

  * `kind` (nullable String) on document_attachments and accounts_payable_attachments
    -- the named slot a file fills (e.g. 'signed_pr'), NULL for an unlabeled 'Other'.
  * `approved_incomplete_slots` (nullable Text) on the five approvable documents
    -- JSON snapshot of required slots empty at approval time; drives the badge.

All plain nullable columns, no FK, so batch mode is only needed for SQLite's
ALTER limitation. Verify against a COPY of a real database, not a create_all()
test DB (per the project migration rules).
"""
from alembic import op
import sqlalchemy as sa


revision = 'reqatt_0001'
down_revision = 'docatt_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('document_attachments') as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=40), nullable=True))
        batch_op.create_index('ix_document_attachments_kind', ['kind'])

    with op.batch_alter_table('accounts_payable_attachments') as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=40), nullable=True))

    for table in ('purchase_requests', 'purchase_orders', 'receiving_reports',
                  'accounts_payable', 'cash_disbursement_vouchers'):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column('approved_incomplete_slots', sa.Text(), nullable=True))


def downgrade():
    for table in ('cash_disbursement_vouchers', 'accounts_payable', 'receiving_reports',
                  'purchase_orders', 'purchase_requests'):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column('approved_incomplete_slots')

    with op.batch_alter_table('accounts_payable_attachments') as batch_op:
        batch_op.drop_column('kind')

    with op.batch_alter_table('document_attachments') as batch_op:
        batch_op.drop_index('ix_document_attachments_kind')
        batch_op.drop_column('kind')
