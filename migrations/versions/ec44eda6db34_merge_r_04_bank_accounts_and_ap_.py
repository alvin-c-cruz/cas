"""merge R-04 bank_accounts and AP variance-snapshot heads

Revision ID: ec44eda6db34
Revises: 1efb5ef17665, 8242857b00da
Create Date: 2026-07-18 17:04:21.028712

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ec44eda6db34'
down_revision = ('1efb5ef17665', '8242857b00da')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
