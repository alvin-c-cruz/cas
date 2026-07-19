"""merge R-07 D1 work-centers/routing and petty-cash control-account-name-fix heads

Revision ID: 47507deefc6f
Revises: 97ec45ed7eb1, b10009747c18
Create Date: 2026-07-19 11:02:30.215258

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '47507deefc6f'
down_revision = ('97ec45ed7eb1', 'b10009747c18')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
