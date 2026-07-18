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
