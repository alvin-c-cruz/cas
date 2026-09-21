"""Named print layouts, and the per-workstation selection.

Purely ADDITIVE — two new tables, nothing altered. create_table needs no batch
wrapper; every FK is NAMED so a later batch rebuild can reproduce it.

Revision ID: prnlay_0001
Revises: apamd_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'prnlay_0001'
down_revision = 'apamd_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'named_print_layouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doc_type', sa.String(length=40), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_named_print_layouts'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name='fk_named_print_layouts_created_by'),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], name='fk_named_print_layouts_updated_by'),
        sa.UniqueConstraint('doc_type', 'scope_id', 'name', name='uq_named_print_layouts_name'),
    )
    op.create_index('ix_named_print_layouts_doc_type', 'named_print_layouts', ['doc_type'])
    # Partial unique index -- raw DDL because Alembic's create_index has no
    # cross-dialect partial-index argument and this is SQLite only.
    op.execute('CREATE UNIQUE INDEX uq_named_print_layouts_one_default '
               'ON named_print_layouts (doc_type, scope_id) WHERE is_default = 1')

    op.create_table(
        'named_print_layout_device_prefs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.String(length=64), nullable=False),
        sa.Column('doc_type', sa.String(length=40), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('layout_id', sa.Integer(), nullable=True),
        sa.Column('label', sa.String(length=100), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_named_print_layout_device_prefs'),
        sa.ForeignKeyConstraint(['layout_id'], ['named_print_layouts.id'],
                                name='fk_named_print_layout_device_prefs_layout',
                                ondelete='SET NULL'),
        sa.UniqueConstraint('device_id', 'doc_type', 'scope_id',
                            name='uq_named_print_layout_device_prefs'),
    )
    op.create_index('ix_named_print_layout_device_prefs_device', 'named_print_layout_device_prefs',
                    ['device_id'])


def downgrade():
    op.drop_index('ix_named_print_layout_device_prefs_device',
                  table_name='named_print_layout_device_prefs')
    op.drop_table('named_print_layout_device_prefs')
    op.execute('DROP INDEX IF EXISTS uq_named_print_layouts_one_default')
    op.drop_index('ix_named_print_layouts_doc_type', table_name='named_print_layouts')
    op.drop_table('named_print_layouts')
