"""merge R-04 petty-cash and R-05 depreciation-run heads

Revision ID: 041eda0bb5ad
Revises: 914f97cdfb0e, fadepr_0001
Create Date: 2026-07-18 23:51:55.903846

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '041eda0bb5ad'
down_revision = ('914f97cdfb0e', 'fadepr_0001')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
