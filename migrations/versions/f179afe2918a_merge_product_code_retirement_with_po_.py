"""merge product-code retirement with PO-less receiving reports

Revision ID: f179afe2918a
Revises: prodcode_0001, rrreason_0001
Create Date: 2026-09-10 09:45:12.372592

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f179afe2918a'
down_revision = ('prodcode_0001', 'rrreason_0001')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
