"""Depreciation run models (R-05 Slice 2).

A DepreciationRun is an explicit, accountant-triggered, per-branch/per-period
computation that posts one account-grouped JE (Dr Depreciation Expense per
distinct expense account / Cr Accumulated Depreciation per distinct accum-dep
account). See docs/superpowers/specs/2026-07-18-fixed-asset-depreciation-design.md.
"""
from app import db
from app.utils import ph_now


class DepreciationRun(db.Model):
    __tablename__ = 'depreciation_runs'
    __table_args__ = (
        db.Index(
            'uq_depreciation_run_period', 'branch_id', 'period_year', 'period_month',
            unique=True,
            sqlite_where=db.text("status != 'reversed'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)  # 1-12

    status = db.Column(db.String(10), default='draft', nullable=False)
    # 'draft' | 'posted' | 'reversed' -- this plan only ever writes 'posted' or
    # 'reversed' directly (there is no draft-then-edit step; the preview step
    # before Task 6/7's confirm-post never creates a row at all).

    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    run_date = db.Column(db.DateTime, default=ph_now, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    entries = db.relationship('DepreciationEntry', backref='run', lazy='dynamic',
                              cascade='all, delete-orphan')

    def __repr__(self):
        return f'<DepreciationRun {self.branch_id}/{self.period_year}-{self.period_month:02d} {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'branch_id': self.branch_id,
            'period_year': self.period_year,
            'period_month': self.period_month,
            'status': self.status,
            'journal_entry_id': self.journal_entry_id,
            'run_date': self.run_date.isoformat() if self.run_date else None,
            'created_by_id': self.created_by_id,
        }


class DepreciationEntry(db.Model):
    __tablename__ = 'depreciation_entries'

    id = db.Column(db.Integer, primary_key=True)

    run_id = db.Column(db.Integer, db.ForeignKey('depreciation_runs.id'), nullable=False,
                       index=True)

    fixed_asset_id = db.Column(db.Integer, db.ForeignKey('fixed_assets.id'), nullable=False,
                               index=True)
    fixed_asset = db.relationship('FixedAsset', foreign_keys=[fixed_asset_id])

    depreciation_amount = db.Column(db.Numeric(15, 2), nullable=False)
    accumulated_depreciation_after = db.Column(db.Numeric(15, 2), nullable=False)
    net_book_value_after = db.Column(db.Numeric(15, 2), nullable=False)
    units_used = db.Column(db.Numeric(15, 2), nullable=True)  # units-of-production only

    def __repr__(self):
        return f'<DepreciationEntry run={self.run_id} asset={self.fixed_asset_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'run_id': self.run_id,
            'fixed_asset_id': self.fixed_asset_id,
            'depreciation_amount': float(self.depreciation_amount),
            'accumulated_depreciation_after': float(self.accumulated_depreciation_after),
            'net_book_value_after': float(self.net_book_value_after),
            'units_used': float(self.units_used) if self.units_used is not None else None,
        }
