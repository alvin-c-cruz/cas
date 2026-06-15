"""rename purchase_bills to accounts_payable (tables + columns)

Also merges the two open migration heads (afc774328cb2, e5f0b6c3d9a1) into a
single head so the revision tree is linear again.

Renames:
  purchase_bills              -> accounts_payable        (bill_number->ap_number, bill_date->ap_date)
  purchase_bill_items         -> accounts_payable_items  (bill_id->ap_id)
  purchase_bill_attachments   -> accounts_payable_attachments (bill_id->ap_id)
  cdv_ap_lines (unchanged name): bill_id->ap_id, bill_number->ap_number

Revision ID: ap20260615rn01
Revises: afc774328cb2, e5f0b6c3d9a1
Create Date: 2026-06-15

Note (PythonAnywhere / production): after `flask db upgrade`, manually rename the
upload folder `instance/uploads/purchase_bills/` to
`instance/uploads/accounts_payable/` to preserve existing attachments.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ap20260615rn01'
down_revision = ('afc774328cb2', 'e5f0b6c3d9a1')
branch_labels = None
depends_on = None


def upgrade():
    # Rename the parent table first; SQLite (>=3.25) updates child-table FK
    # references automatically, and the subsequent batch recreations reflect
    # the corrected references.
    # 1. purchase_bills -> accounts_payable; rename bill_number, bill_date
    op.rename_table('purchase_bills', 'accounts_payable')
    with op.batch_alter_table('accounts_payable') as batch_op:
        batch_op.alter_column('bill_number', new_column_name='ap_number')
        batch_op.alter_column('bill_date', new_column_name='ap_date')

    # 2. purchase_bill_items -> accounts_payable_items; rename bill_id -> ap_id
    op.rename_table('purchase_bill_items', 'accounts_payable_items')
    with op.batch_alter_table('accounts_payable_items') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')

    # 3. purchase_bill_attachments -> accounts_payable_attachments; rename bill_id -> ap_id
    op.rename_table('purchase_bill_attachments', 'accounts_payable_attachments')
    with op.batch_alter_table('accounts_payable_attachments') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')

    # 4. cdv_ap_lines -- rename bill_id, bill_number (table name unchanged)
    with op.batch_alter_table('cdv_ap_lines') as batch_op:
        batch_op.alter_column('bill_id', new_column_name='ap_id')
        batch_op.alter_column('bill_number', new_column_name='ap_number')


def downgrade():
    with op.batch_alter_table('cdv_ap_lines') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')
        batch_op.alter_column('ap_number', new_column_name='bill_number')

    with op.batch_alter_table('accounts_payable_attachments') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')
    op.rename_table('accounts_payable_attachments', 'purchase_bill_attachments')

    with op.batch_alter_table('accounts_payable_items') as batch_op:
        batch_op.alter_column('ap_id', new_column_name='bill_id')
    op.rename_table('accounts_payable_items', 'purchase_bill_items')

    with op.batch_alter_table('accounts_payable') as batch_op:
        batch_op.alter_column('ap_number', new_column_name='bill_number')
        batch_op.alter_column('ap_date', new_column_name='bill_date')
    op.rename_table('accounts_payable', 'purchase_bills')
