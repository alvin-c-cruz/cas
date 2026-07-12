"""
Statutory payroll master-data models for Philippine tax compliance.
SSS, PhilHealth, Pag-IBIG, and Compensation WHT contribution/rate tables.
"""

from app import db
from app.utils import ph_now


class SSSContributionTable(db.Model):
    """SSS contribution salary table with salary brackets and contribution amounts."""
    __tablename__ = 'sss_contribution_tables'

    id = db.Column(db.Integer, primary_key=True)
    effective_from = db.Column(db.Date, nullable=False, index=True)
    effective_to = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    rows = db.relationship('SSSContributionRow', backref='table',
                           cascade='all, delete-orphan', order_by='SSSContributionRow.comp_from')


class SSSContributionRow(db.Model):
    """A salary bracket within an SSS contribution table."""
    __tablename__ = 'sss_contribution_rows'

    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('sss_contribution_tables.id'), nullable=False, index=True)

    # Salary bracket (inclusive lower, nullable upper = open-ended top bracket)
    comp_from = db.Column(db.Numeric(15, 2), nullable=False)
    comp_to = db.Column(db.Numeric(15, 2))

    # Contribution amounts and components
    msc = db.Column(db.Numeric(15, 2), nullable=False)  # Monthly Salary Credit
    ee_amount = db.Column(db.Numeric(15, 2), nullable=False)  # Employee contribution
    er_amount = db.Column(db.Numeric(15, 2), nullable=False)  # Employer contribution
    ee_wisp = db.Column(db.Numeric(15, 2), default=0, nullable=False)  # Employee WISP
    er_wisp = db.Column(db.Numeric(15, 2), default=0, nullable=False)  # Employer WISP
    ec_amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)  # EC (Employees' Compensation)


class PhilHealthRate(db.Model):
    """PhilHealth insurance rate table for a period."""
    __tablename__ = 'philhealth_rates'

    id = db.Column(db.Integer, primary_key=True)
    premium_rate = db.Column(db.Numeric(6, 4), nullable=False)  # e.g., 0.0500 for 5%
    income_floor = db.Column(db.Numeric(15, 2), nullable=False)  # Clamped lower bound
    income_ceiling = db.Column(db.Numeric(15, 2), nullable=False)  # Clamped upper bound
    ee_share = db.Column(db.Numeric(6, 4), nullable=False)  # Employee's share of premium

    effective_from = db.Column(db.Date, nullable=False, index=True)
    effective_to = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)


class PagIbigRate(db.Model):
    """Pag-IBIG housing fund contribution rate table."""
    __tablename__ = 'pagibig_rates'

    id = db.Column(db.Integer, primary_key=True)
    bracket_threshold = db.Column(db.Numeric(15, 2), nullable=False)  # Salary threshold
    lower_ee_rate = db.Column(db.Numeric(6, 4), nullable=False)  # Rate for salary <= threshold
    upper_ee_rate = db.Column(db.Numeric(6, 4), nullable=False)  # Rate for salary > threshold
    er_rate = db.Column(db.Numeric(6, 4), nullable=False)  # Employer contribution rate
    mc_ceiling = db.Column(db.Numeric(15, 2), nullable=False)  # Monthly compensation cap

    effective_from = db.Column(db.Date, nullable=False, index=True)
    effective_to = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)


class CompensationWHTBracket(db.Model):
    """Tax bracket for compensation withholding tax (employee income tax)."""
    __tablename__ = 'compensation_wht_brackets'
    __table_args__ = (db.Index('ix_cwht_freq_eff', 'frequency', 'effective_from'),)

    id = db.Column(db.Integer, primary_key=True)
    frequency = db.Column(db.String(20), nullable=False)  # daily/weekly/semi_monthly/monthly
    bracket_no = db.Column(db.Integer, nullable=False)  # 1, 2, 3, etc.

    # Tax bracket (lower bound inclusive; nullable upper = open-ended top bracket)
    lower_bound = db.Column(db.Numeric(15, 2), nullable=False)
    upper_bound = db.Column(db.Numeric(15, 2))

    # Tax calculation
    base_tax = db.Column(db.Numeric(15, 2), nullable=False)  # Minimum tax for this bracket
    rate_on_excess = db.Column(db.Numeric(6, 4), nullable=False)  # Rate on amount above lower_bound

    effective_from = db.Column(db.Date, nullable=False, index=True)
    effective_to = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)


class StatutoryTableChangeRequest(db.Model):
    """Governed-edit request for statutory payroll tables (pending implementation).

    Mirrors the WithholdingTaxChangeRequest pattern: allows accountants to propose
    changes to statutory tables (SSS, PhilHealth, Pag-IBIG, Compensation WHT)
    that require approval before taking effect.
    """
    __tablename__ = 'statutory_table_change_requests'

    id = db.Column(db.Integer, primary_key=True)

    # What type of table and what action
    table_type = db.Column(db.String(30), nullable=False)  # 'sss'/'philhealth'/'pagibig'/'wht'
    target_id = db.Column(db.Integer, nullable=True)  # ID of existing table being updated/deleted
    action = db.Column(db.String(20), nullable=False)  # create/update/delete

    # Status workflow
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending/approved/rejected
    proposed_data = db.Column(db.Text)  # JSON string of proposed field values
    request_reason = db.Column(db.Text)  # Why the change is needed

    # Requester
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    # Reviewer (pending -> approved/rejected)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
