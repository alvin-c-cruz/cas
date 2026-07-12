"""payroll statutory master tables (SSS, PhilHealth, Pag-IBIG, Compensation WHT)

Revision ID: 1a2b3c4d5e6f
Revises: 318ee8bbb515
Create Date: 2026-07-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1a2b3c4d5e6f'
down_revision = '318ee8bbb515'
branch_labels = None
depends_on = None


def upgrade():
    # SSS contribution salary table with brackets
    op.create_table('sss_contribution_tables',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('created_by', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sss_contribution_tables_effective_from', 'sss_contribution_tables',
                    ['effective_from'], unique=False)

    # SSS contribution salary bracket rows
    op.create_table('sss_contribution_rows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('table_id', sa.Integer(), nullable=False),
    sa.Column('comp_from', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('comp_to', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('msc', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('ee_amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('er_amount', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('ee_wisp', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
    sa.Column('er_wisp', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
    sa.Column('ec_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
    sa.ForeignKeyConstraint(['table_id'], ['sss_contribution_tables.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sss_contribution_rows_table_id', 'sss_contribution_rows',
                    ['table_id'], unique=False)

    # PhilHealth insurance rate table
    op.create_table('philhealth_rates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('premium_rate', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('income_floor', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('income_ceiling', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('ee_share', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('created_by', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_philhealth_rates_effective_from', 'philhealth_rates',
                    ['effective_from'], unique=False)

    # Pag-IBIG housing fund contribution rate table
    op.create_table('pagibig_rates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bracket_threshold', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('lower_ee_rate', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('upper_ee_rate', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('er_rate', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('mc_ceiling', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('created_by', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_pagibig_rates_effective_from', 'pagibig_rates',
                    ['effective_from'], unique=False)

    # Compensation withholding tax brackets (per payroll frequency)
    op.create_table('compensation_wht_brackets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('frequency', sa.String(length=20), nullable=False),
    sa.Column('bracket_no', sa.Integer(), nullable=False),
    sa.Column('lower_bound', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('upper_bound', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('base_tax', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('rate_on_excess', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('created_by', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cwht_freq_eff', 'compensation_wht_brackets',
                    ['frequency', 'effective_from'], unique=False)
    op.create_index('ix_compensation_wht_brackets_effective_from', 'compensation_wht_brackets',
                    ['effective_from'], unique=False)

    # Governed-edit change request for statutory tables
    op.create_table('statutory_table_change_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('table_type', sa.String(length=30), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
    sa.Column('proposed_data', sa.Text(), nullable=True),
    sa.Column('request_reason', sa.Text(), nullable=True),
    sa.Column('requested_by_id', sa.Integer(), nullable=False),
    sa.Column('requested_at', sa.DateTime(), nullable=False),
    sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('review_notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('statutory_table_change_requests')
    op.drop_index('ix_compensation_wht_brackets_effective_from', table_name='compensation_wht_brackets')
    op.drop_index('ix_cwht_freq_eff', table_name='compensation_wht_brackets')
    op.drop_table('compensation_wht_brackets')
    op.drop_index('ix_pagibig_rates_effective_from', table_name='pagibig_rates')
    op.drop_table('pagibig_rates')
    op.drop_index('ix_philhealth_rates_effective_from', table_name='philhealth_rates')
    op.drop_table('philhealth_rates')
    op.drop_index('ix_sss_contribution_rows_table_id', table_name='sss_contribution_rows')
    op.drop_table('sss_contribution_rows')
    op.drop_index('ix_sss_contribution_tables_effective_from', table_name='sss_contribution_tables')
    op.drop_table('sss_contribution_tables')
