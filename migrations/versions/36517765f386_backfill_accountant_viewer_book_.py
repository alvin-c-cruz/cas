"""backfill accountant/viewer book_permissions

Revision ID: 36517765f386
Revises: 04f81ff303ca
Create Date: 2026-06-27 10:57:14.411224

"""
# revision identifiers, used by Alembic.
revision = '36517765f386'
down_revision = '04f81ff303ca'
branch_labels = None
depends_on = None


def upgrade():
    from app import db
    from app.users.migrations_support import backfill_book_permissions
    backfill_book_permissions(db.session)
    db.session.commit()


def downgrade():
    # Data backfill — nothing to reverse (permissions become user-managed state).
    pass
