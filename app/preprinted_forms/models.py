"""Per-voucher pre-printed form layout (positions of data fields on a physical form)."""
import json
from app import db
from app.utils import ph_now

VOUCHER_TYPES = ('SI', 'CR', 'CD', 'AP', 'JV')

VOUCHER_LABELS = {
    'SI': 'Sales Invoice',
    'CR': 'Cash Receipt Voucher',
    'CD': 'Cash Disbursement Voucher',
    'AP': 'Accounts Payable Voucher',
    'JV': 'Journal Voucher',
}


class PrintLayout(db.Model):
    __tablename__ = 'print_layouts'
    __table_args__ = (
        db.UniqueConstraint('voucher_type', 'account_id',
                            name='uq_print_layouts_voucher_type_account_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    voucher_type = db.Column(db.String(16), nullable=False, index=True)  # SI/CR/CD/AP/JV/CD_CHECK
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True, index=True)  # NULL = Default
    active = db.Column(db.Boolean, default=False, nullable=False)  # admin pre-printed toggle
    background_image = db.Column(db.String(200), nullable=True)    # filename under instance/uploads/preprinted
    page_width_mm = db.Column(db.Numeric(6, 2), default=215.90, nullable=False)
    page_height_mm = db.Column(db.Numeric(6, 2), default=279.40, nullable=False)
    fields_json = db.Column(db.Text, default='[]')
    line_band_json = db.Column(db.Text, default='{}')
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by = db.Column(db.String(80))

    def get_fields(self):
        try:
            return json.loads(self.fields_json) if self.fields_json else []
        except (ValueError, TypeError):
            return []

    def set_fields(self, value):
        self.fields_json = json.dumps(value)

    def get_line_band(self):
        try:
            return json.loads(self.line_band_json) if self.line_band_json else {}
        except (ValueError, TypeError):
            return {}

    def set_line_band(self, value):
        self.line_band_json = json.dumps(value)
