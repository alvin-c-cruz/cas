"""Fixed Asset register models (R-05 Slice 1).

A FixedAsset is a subledger entry that TAGS an already-posted AP-bill / CDV / JV
line as capitalized -- it posts no journal entry of its own. See
docs/superpowers/specs/2026-07-18-fixed-asset-register-design.md.
"""
from app import db
from app.utils import ph_now

DEPRECIATION_METHODS = ('straight_line', 'declining_balance', 'units_of_production')
ACQUISITION_SOURCE_TYPES = ('ap_bill', 'cdv', 'jv', 'opening')


class AssetCategory(db.Model):
    """Lightweight classification tag for fixed assets. Carries NO GL accounts --
    those are assigned per-asset. Mirrors the ProductCategory CRUD pattern."""
    __tablename__ = 'asset_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    default_useful_life_months = db.Column(db.Integer, nullable=True)
    default_depreciation_method = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    def __repr__(self):
        return f'<AssetCategory {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'default_useful_life_months': self.default_useful_life_months,
            'default_depreciation_method': self.default_depreciation_method,
            'is_active': self.is_active,
        }


class FixedAsset(db.Model):
    """A fixed asset register row. Tags an already-posted AP-bill/CDV/JV line as
    capitalized (acquisition_source_type != 'opening') or captures a pre-CAS
    asset directly (acquisition_source_type == 'opening'). Posts NO journal
    entry of its own -- cost_account_id is read from the tagged line."""
    __tablename__ = 'fixed_assets'
    __table_args__ = (
        db.Index(
            'uq_fixed_assets_acquisition_source',
            'acquisition_source_type', 'acquisition_source_id', 'acquisition_source_line_id',
            unique=True,
            sqlite_where=db.text("acquisition_source_type != 'opening'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)

    category_id = db.Column(db.Integer, db.ForeignKey('asset_categories.id'), nullable=True)
    category = db.relationship('AssetCategory', foreign_keys=[category_id])

    # Acquisition / tagging
    acquisition_source_type = db.Column(db.String(10), nullable=False)
    acquisition_source_id = db.Column(db.Integer, nullable=True)
    acquisition_source_line_id = db.Column(db.Integer, nullable=True)
    acquisition_date = db.Column(db.Date, nullable=False)
    acquisition_cost = db.Column(db.Numeric(15, 2), nullable=False)

    # GL accounts -- cost_account_id is IMMUTABLE after creation (derived from the
    # tagged line, or chosen once for an opening asset). The other two are
    # chosen per-asset (no category-level default, per the locked design decision).
    cost_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    cost_account = db.relationship('Account', foreign_keys=[cost_account_id])
    accumulated_depreciation_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'),
                                                     nullable=False)
    accumulated_depreciation_account = db.relationship(
        'Account', foreign_keys=[accumulated_depreciation_account_id])
    depreciation_expense_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'),
                                                 nullable=False)
    depreciation_expense_account = db.relationship(
        'Account', foreign_keys=[depreciation_expense_account_id])

    # Depreciation configuration (consumed by Slice 2 — not run here)
    depreciation_method = db.Column(db.String(20), nullable=False)
    useful_life_months = db.Column(db.Integer, nullable=True)
    declining_balance_rate = db.Column(db.Numeric(5, 2), nullable=True)
    total_estimated_units = db.Column(db.Numeric(15, 2), nullable=True)
    salvage_value = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    # Only meaningful when acquisition_source_type == 'opening'
    opening_accumulated_depreciation = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    status = db.Column(db.String(10), default='active', nullable=False, index=True)
    # 'active' | 'disposed' (disposed flips in Slice 3)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    def __repr__(self):
        return f'<FixedAsset {self.code}>'

    @property
    def accumulated_depreciation(self):
        """opening_accumulated_depreciation plus every posted DepreciationEntry
        for this asset (Slice 2). A reversed run's entries are excluded -- the
        DepreciationEntry rows themselves are never deleted on reversal (they
        stay as a historical record of what that run computed), so the query
        filters by the owning DepreciationRun.status, not row presence."""
        from decimal import Decimal
        from app import db
        from app.fixed_asset_depreciation.models import DepreciationRun, DepreciationEntry
        posted_total = db.session.query(
            db.func.coalesce(db.func.sum(DepreciationEntry.depreciation_amount), 0)
        ).join(DepreciationRun, DepreciationEntry.run_id == DepreciationRun.id).filter(
            DepreciationEntry.fixed_asset_id == self.id,
            DepreciationRun.status == 'posted',
        ).scalar()
        return Decimal(str(self.opening_accumulated_depreciation)) + Decimal(str(posted_total))

    @property
    def net_book_value(self):
        from decimal import Decimal
        return Decimal(str(self.acquisition_cost)) - Decimal(str(self.accumulated_depreciation))

    def to_dict(self):
        return {
            'id': self.id,
            'branch_id': self.branch_id,
            'code': self.code,
            'name': self.name,
            'category_id': self.category_id,
            'category_name': self.category.name if self.category else None,
            'acquisition_source_type': self.acquisition_source_type,
            'acquisition_source_id': self.acquisition_source_id,
            'acquisition_source_line_id': self.acquisition_source_line_id,
            'acquisition_date': self.acquisition_date.isoformat() if self.acquisition_date else None,
            'acquisition_cost': float(self.acquisition_cost),
            'cost_account_id': self.cost_account_id,
            'cost_account_code': self.cost_account.code if self.cost_account else None,
            'accumulated_depreciation_account_id': self.accumulated_depreciation_account_id,
            'depreciation_expense_account_id': self.depreciation_expense_account_id,
            'depreciation_method': self.depreciation_method,
            'useful_life_months': self.useful_life_months,
            'declining_balance_rate': (float(self.declining_balance_rate)
                                       if self.declining_balance_rate is not None else None),
            'total_estimated_units': (float(self.total_estimated_units)
                                      if self.total_estimated_units is not None else None),
            'salvage_value': float(self.salvage_value),
            'opening_accumulated_depreciation': float(self.opening_accumulated_depreciation),
            'net_book_value': float(self.net_book_value),
            'status': self.status,
        }
