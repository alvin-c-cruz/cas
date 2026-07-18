"""Fixed asset disposal model (R-05 Slice 3). See
docs/superpowers/specs/2026-07-18-fixed-asset-disposal-design.md."""
from app import db
from app.utils import ph_now

DISPOSAL_TYPES = ('sale', 'scrap', 'trade_in')


class FixedAssetDisposal(db.Model):
    __tablename__ = 'fixed_asset_disposals'
    __table_args__ = (
        db.Index(
            'uq_fixed_asset_disposal_asset', 'fixed_asset_id',
            unique=True,
            sqlite_where=db.text("status != 'void'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    fixed_asset_id = db.Column(db.Integer, db.ForeignKey('fixed_assets.id'), nullable=False,
                               index=True)
    fixed_asset = db.relationship('FixedAsset', foreign_keys=[fixed_asset_id])

    disposal_date = db.Column(db.Date, nullable=False)
    disposal_type = db.Column(db.String(10), nullable=False)  # sale | scrap | trade_in

    proceeds_amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    proceeds_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    proceeds_account = db.relationship('Account', foreign_keys=[proceeds_account_id])

    final_depreciation_amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    cost_written_off = db.Column(db.Numeric(15, 2), nullable=False)
    accumulated_depreciation_written_off = db.Column(db.Numeric(15, 2), nullable=False)
    net_book_value_at_disposal = db.Column(db.Numeric(15, 2), nullable=False)
    gain_loss_amount = db.Column(db.Numeric(15, 2), nullable=False)

    status = db.Column(db.String(10), default='posted', nullable=False)  # posted | void

    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    notes = db.Column(db.Text, nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    def __repr__(self):
        return f'<FixedAssetDisposal asset={self.fixed_asset_id} {self.disposal_type} {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'fixed_asset_id': self.fixed_asset_id,
            'disposal_date': self.disposal_date.isoformat() if self.disposal_date else None,
            'disposal_type': self.disposal_type,
            'proceeds_amount': float(self.proceeds_amount),
            'proceeds_account_id': self.proceeds_account_id,
            'final_depreciation_amount': float(self.final_depreciation_amount),
            'cost_written_off': float(self.cost_written_off),
            'accumulated_depreciation_written_off': float(self.accumulated_depreciation_written_off),
            'net_book_value_at_disposal': float(self.net_book_value_at_disposal),
            'gain_loss_amount': float(self.gain_loss_amount),
            'status': self.status,
            'journal_entry_id': self.journal_entry_id,
        }
