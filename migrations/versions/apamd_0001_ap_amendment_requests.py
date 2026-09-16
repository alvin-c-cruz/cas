"""AP attachment amendment requests: edit-level ask, approvers commit the file.

Purely ADDITIVE — one new table, no existing table altered. create_table needs no
batch wrapper; all FKs are NAMED so a later batch rebuild can reproduce them.

Revision ID: apamd_0001
Revises: reqatt_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'apamd_0001'
down_revision = 'reqatt_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ap_amendment_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ap_id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('staged_original_filename', sa.String(length=255), nullable=False),
        sa.Column('staged_stored_filename', sa.String(length=255), nullable=False),
        sa.Column('staged_mime_type', sa.String(length=100), nullable=False),
        sa.Column('staged_file_size', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id', name='pk_ap_amendment_requests'),
        sa.ForeignKeyConstraint(['ap_id'], ['accounts_payable.id'], name='fk_ap_amend_req_ap'),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name='fk_ap_amend_req_branch'),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], name='fk_ap_amend_req_requested_by'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], name='fk_ap_amend_req_reviewed_by'),
    )
    op.create_index('ix_ap_amendment_requests_ap_id', 'ap_amendment_requests', ['ap_id'])
    op.create_index('ix_ap_amendment_requests_branch_id', 'ap_amendment_requests', ['branch_id'])
    op.create_index('ix_ap_amendment_requests_status', 'ap_amendment_requests', ['status'])
    op.create_index('ix_ap_amend_req_pending', 'ap_amendment_requests', ['ap_id', 'status'])


def downgrade():
    op.drop_index('ix_ap_amend_req_pending', table_name='ap_amendment_requests')
    op.drop_index('ix_ap_amendment_requests_status', table_name='ap_amendment_requests')
    op.drop_index('ix_ap_amendment_requests_branch_id', table_name='ap_amendment_requests')
    op.drop_index('ix_ap_amendment_requests_ap_id', table_name='ap_amendment_requests')
    op.drop_table('ap_amendment_requests')
