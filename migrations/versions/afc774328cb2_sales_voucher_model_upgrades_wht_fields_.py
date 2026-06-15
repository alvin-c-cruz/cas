"""sales voucher model upgrades — WHT fields, journal entry FK, attachments, output vat account

Revision ID: afc774328cb2
Revises: 77c2e66f3325
Create Date: 2026-06-14 16:15:16.414465

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'afc774328cb2'
down_revision = '77c2e66f3325'
branch_labels = None
depends_on = None


def upgrade():
    # Create sales_invoice_attachments table (only if it doesn't exist yet)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'sales_invoice_attachments' not in inspector.get_table_names():
        op.create_table('sales_invoice_attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_filename', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['sales_invoices.id'], ),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stored_filename')
        )
    # Create index if not already present
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('sales_invoice_attachments')]
    if 'ix_sales_invoice_attachments_invoice_id' not in existing_indexes:
        with op.batch_alter_table('sales_invoice_attachments', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_sales_invoice_attachments_invoice_id'), ['invoice_id'], unique=False)

    # Upgrade sales_invoice_items: add WHT columns, drop quantity/unit_price
    with op.batch_alter_table('sales_invoice_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False,
                                      server_default='0.00'))
        batch_op.add_column(sa.Column('wt_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('wt_rate', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('wt_amount', sa.Numeric(precision=15, scale=2), nullable=False,
                                      server_default='0.00'))
        batch_op.create_foreign_key('fk_sii_wt_id', 'withholding_tax', ['wt_id'], ['id'])
        batch_op.drop_column('quantity')
        batch_op.drop_column('unit_price')

    # Upgrade sales_invoices: add new columns
    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_po_number', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('customer_po_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('total_before_wt', sa.Numeric(precision=15, scale=2), nullable=False,
                                      server_default='0.00'))
        batch_op.add_column(sa.Column('withholding_tax_amount', sa.Numeric(precision=15, scale=2), nullable=False,
                                      server_default='0.00'))
        batch_op.add_column(sa.Column('vat_override', sa.Boolean(), nullable=False,
                                      server_default='0'))
        batch_op.add_column(sa.Column('wt_override', sa.Boolean(), nullable=False,
                                      server_default='0'))
        batch_op.add_column(sa.Column('journal_entry_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cancel_reason', sa.String(length=500), nullable=True))
        # Backfill NULL notes before making NOT NULL
        op.execute("UPDATE sales_invoices SET notes = '' WHERE notes IS NULL")
        batch_op.alter_column('notes',
               existing_type=sa.TEXT(),
               nullable=False,
               server_default='')
        batch_op.create_foreign_key('fk_si_journal_entry_id', 'journal_entries', ['journal_entry_id'], ['id'])

    # Add output_vat_account_id to vat_categories
    with op.batch_alter_table('vat_categories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('output_vat_account_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_vatcat_output_vat_account_id', 'accounts', ['output_vat_account_id'], ['id'])


def downgrade():
    with op.batch_alter_table('vat_categories', schema=None) as batch_op:
        batch_op.drop_constraint('fk_vatcat_output_vat_account_id', type_='foreignkey')
        batch_op.drop_column('output_vat_account_id')

    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.drop_constraint('fk_si_journal_entry_id', type_='foreignkey')
        batch_op.alter_column('notes',
               existing_type=sa.TEXT(),
               nullable=True)
        batch_op.drop_column('cancel_reason')
        batch_op.drop_column('journal_entry_id')
        batch_op.drop_column('wt_override')
        batch_op.drop_column('vat_override')
        batch_op.drop_column('withholding_tax_amount')
        batch_op.drop_column('total_before_wt')
        batch_op.drop_column('customer_po_date')
        batch_op.drop_column('customer_po_number')

    with op.batch_alter_table('sales_invoice_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unit_price', sa.NUMERIC(precision=15, scale=2), nullable=False,
                                      server_default='0.00'))
        batch_op.add_column(sa.Column('quantity', sa.NUMERIC(precision=15, scale=4), nullable=False,
                                      server_default='1.0000'))
        batch_op.drop_constraint('fk_sii_wt_id', type_='foreignkey')
        batch_op.drop_column('wt_amount')
        batch_op.drop_column('wt_rate')
        batch_op.drop_column('wt_id')
        batch_op.drop_column('amount')

    with op.batch_alter_table('sales_invoice_attachments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_invoice_attachments_invoice_id'))

    op.drop_table('sales_invoice_attachments')
