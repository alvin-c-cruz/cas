"""backfill accountant branches

Revision ID: c6aaf3c5c0fa
Revises: 78bed40214ed
Create Date: 2026-06-27 05:22:48.986953

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6aaf3c5c0fa'
down_revision = '78bed40214ed'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO user_branches (user_id, branch_id)
        SELECT u.id, b.id FROM users u CROSS JOIN branches b
        WHERE u.role = 'accountant' AND b.is_active = 1
          AND NOT EXISTS (
              SELECT 1 FROM user_branches ub
              WHERE ub.user_id = u.id
          )
    """)


def downgrade():
    pass
