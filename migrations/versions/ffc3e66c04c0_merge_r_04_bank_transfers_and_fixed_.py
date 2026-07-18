"""merge R-04 bank-transfers and fixed-asset-register/job-order-slips heads

Revision ID: ffc3e66c04c0
Revises: 35704cb242d1, 521eed6b3e9e
Create Date: 2026-07-18 20:20:49.757660

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ffc3e66c04c0'
down_revision = ('35704cb242d1', '521eed6b3e9e')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
