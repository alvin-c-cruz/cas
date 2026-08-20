"""Purchase Requisition amendment requests: staff ask, approvers apply.

Purely ADDITIVE -- one new table, no column added to or altered on any existing
table. Nothing about an existing requisition changes, so a client that never uses
the feature is byte-identical afterwards.

Hand-written (this repo configures Migrate() without render_as_batch, so autogen
emits plain ALTERs SQLite cannot run). `create_table` needs no batch wrapper --
batch mode exists for ALTERing an existing table, which this migration never does.

The two FKs to users.id are NAMED explicitly. An unnamed FK is fine inside
create_table, but naming both keeps a later batch rebuild of this table able to
reproduce them -- the unnamed-constraint trap recorded in projects/cas/CLAUDE.md.

Revision ID: pramd_0001
Revises: popurp_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'pramd_0001'
down_revision = 'popurp_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pr_amendment_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('purchase_request_id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_id', sa.Integer(), nullable=False),
        sa.Column('request_reason', sa.Text(), nullable=False),
        sa.Column('proposed_json', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='pending'),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('applied_revision_number', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        # RowVersioned's column: the optimistic-lock guard for approve/reject.
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id', name='pk_pr_amendment_requests'),
        sa.ForeignKeyConstraint(['purchase_request_id'], ['purchase_requests.id'],
                                name='fk_pr_amend_req_purchase_request'),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'],
                                name='fk_pr_amend_req_branch'),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'],
                                name='fk_pr_amend_req_requested_by'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'],
                                name='fk_pr_amend_req_reviewed_by'),
    )
    op.create_index('ix_pr_amendment_requests_purchase_request_id',
                    'pr_amendment_requests', ['purchase_request_id'])
    op.create_index('ix_pr_amendment_requests_branch_id',
                    'pr_amendment_requests', ['branch_id'])
    op.create_index('ix_pr_amendment_requests_status',
                    'pr_amendment_requests', ['status'])
    # The hot path: "does this requisition have a pending request?" is asked by
    # the convert guard on every conversion attempt.
    op.create_index('ix_pr_amend_req_pending', 'pr_amendment_requests',
                    ['purchase_request_id', 'status'])


def downgrade():
    op.drop_index('ix_pr_amend_req_pending', table_name='pr_amendment_requests')
    op.drop_index('ix_pr_amendment_requests_status', table_name='pr_amendment_requests')
    op.drop_index('ix_pr_amendment_requests_branch_id', table_name='pr_amendment_requests')
    op.drop_index('ix_pr_amendment_requests_purchase_request_id',
                  table_name='pr_amendment_requests')
    op.drop_table('pr_amendment_requests')
