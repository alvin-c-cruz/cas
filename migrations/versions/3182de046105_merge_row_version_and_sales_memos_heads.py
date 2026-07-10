"""merge row_version and sales_memos heads

Revision ID: 3182de046105
Revises: 7f2b9c31ad04, a7c3f1e9b2d4
Create Date: 2026-07-10 07:56:36.118040

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3182de046105'
down_revision = ('7f2b9c31ad04', 'a7c3f1e9b2d4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
