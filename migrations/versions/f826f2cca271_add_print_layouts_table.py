"""add print_layouts table

Revision ID: f826f2cca271
Revises: 1195af048f68
Create Date: 2026-07-02 05:34:17.863914

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f826f2cca271'
down_revision = '1195af048f68'
branch_labels = None
depends_on = None


def upgrade():
    # Autogenerate also proposed pre-existing drift (drop dead 'receipts' table;
    # rename stale ix_purchase_bill* indexes) — intentionally excluded; tracked
    # as backlog housekeeping.
    op.create_table('print_layouts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('voucher_type', sa.String(length=8), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('background_image', sa.String(length=200), nullable=True),
    sa.Column('page_width_mm', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('page_height_mm', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('fields_json', sa.Text(), nullable=True),
    sa.Column('line_band_json', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('updated_by', sa.String(length=80), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('print_layouts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_print_layouts_voucher_type'), ['voucher_type'], unique=True)


def downgrade():
    with op.batch_alter_table('print_layouts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_print_layouts_voucher_type'))

    op.drop_table('print_layouts')
