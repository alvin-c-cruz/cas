"""bug reports: the "Report a problem" button (ported from Sanay)

Two new tables, nothing existing is touched:

  bug_reports        one row per report: message, context JSON, status, closed_at
  bug_report_images  one row per picture; the file is UPLOAD_FOLDER/bug_reports/<report id>/<stored_name>

No branch_id on purpose: a bug report is not an accounting record, and a branch_id would make the
mapper-derived branch-delete guard refuse branch deletes over bug reports. Constraints are named so
a later batch rebuild can reproduce them.

Revision ID: bugrep_0001
Revises: rrsettle_0001
Create Date: 2026-10-15

"""
from alembic import op
import sqlalchemy as sa


revision = 'bugrep_0001'
down_revision = 'rrsettle_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'bug_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='new'),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('context', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_bug_reports'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_bug_reports_user_id'),
    )
    op.create_index('ix_bug_reports_status', 'bug_reports', ['status'])
    # The daily-limit count: this user's reports in the last 24 hours.
    op.create_index('ix_bug_reports_user_created', 'bug_reports', ['user_id', 'created_at'])

    op.create_table(
        'bug_report_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('mime', sa.String(length=20), nullable=False),
        sa.Column('stored_name', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_bug_report_images'),
        sa.ForeignKeyConstraint(['report_id'], ['bug_reports.id'],
                                name='fk_bug_report_images_report_id'),
    )
    op.create_index('ix_bug_report_images_report_id', 'bug_report_images', ['report_id'])


def downgrade():
    """Drops both tables. Picture files under UPLOAD_FOLDER/bug_reports/ are left on disk;
    delete that folder by hand if the feature is being removed for good."""
    op.drop_index('ix_bug_report_images_report_id', table_name='bug_report_images')
    op.drop_table('bug_report_images')
    op.drop_index('ix_bug_reports_user_created', table_name='bug_reports')
    op.drop_index('ix_bug_reports_status', table_name='bug_reports')
    op.drop_table('bug_reports')
