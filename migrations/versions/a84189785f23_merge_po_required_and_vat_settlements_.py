"""merge po_required and vat_settlements heads

Revision ID: a84189785f23
Revises: a75a26b82c7f, d76332c9c780
Create Date: 2026-07-09 08:50:33.930392

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a84189785f23'
down_revision = ('a75a26b82c7f', 'd76332c9c780')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
