"""merge fixed_asset_register and job_order_slips heads

Revision ID: 521eed6b3e9e
Revises: fxdasset_0001, 7f2a91cd44be
Create Date: 2026-07-18 20:18:27.932948

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '521eed6b3e9e'
down_revision = ('fxdasset_0001', '7f2a91cd44be')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
