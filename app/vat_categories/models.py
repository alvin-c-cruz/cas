"""
VAT Category models for Philippine BIR compliance
"""
from app import db
from datetime import datetime
from app.utils import ph_now


# BIR 2550Q Part II purchase classifier. Mirrors SalesVATCategory.transaction_nature
# on the sales side, but nullable: there is no purchase-side "regular", and an
# unrecognized legacy code must stay honestly unclassified rather than be guessed.
PURCHASE_NATURES = (
    'capital_goods',         # 2550Q 18A/18B (not split at 1,000,000)
    'domestic_goods',        # 18C
    'domestic_services',     # 18E
    'importation',           # 18D
    'nonresident_services',  # 18F -- selectable, unseeded
    'exempt',                # exempt purchases
    'zero_rated',            # zero-rated purchases
    'not_qualified',         # 18G -- no input tax
)

# Seeded-code -> nature. Covers the standard 7-code seed and the legacy 4-code
# seed (seed_data.py::seed_vat_categories). Unlisted codes are client-created and
# resolve to NULL.
PURCHASE_NATURE_BY_CODE = {
    'V12CG': 'capital_goods',
    'V12DG': 'domestic_goods',
    'V12SV': 'domestic_services',
    'V12IM': 'importation',
    'VEX': 'exempt',
    'V0': 'zero_rated',
    'INV': 'not_qualified',
    'VATABLE': 'domestic_goods',
    'VAT-EXEMPT': 'exempt',
    'ZERO-RATED': 'zero_rated',
    'NON-VAT': 'not_qualified',
}


class VATCategory(db.Model):
    """VAT Category master table (shared across branches)"""
    __tablename__ = 'vat_categories'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    rate = db.Column(db.Numeric(5, 2), nullable=False)  # e.g., 12.00 for 12%
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # BIR 2550Q Part II classifier. NULL = unclassified (legacy rows only).
    transaction_nature = db.Column(db.String(30), nullable=True)

    # Input VAT account used for purchase journal entries (B-014).
    # NULL is correct for zero-rate categories; the form requires it when rate > 0.
    input_vat_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'),
                                     nullable=True)

    # Audit fields
    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='vat_categories_created')
    updated_by = db.relationship('User', foreign_keys=[updated_by_id], backref='vat_categories_updated')
    input_vat_account = db.relationship('Account', foreign_keys=[input_vat_account_id])

    def __repr__(self):
        return f'<VATCategory {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'rate': float(self.rate) if self.rate else 0.0,
            'transaction_nature': self.transaction_nature,
            'input_vat_account_id': self.input_vat_account_id,
            'input_vat_account_code': self.input_vat_account.code if self.input_vat_account else None,
            'input_vat_account_name': self.input_vat_account.name if self.input_vat_account else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class VATCategoryChangeRequest(db.Model):
    """Change request table for VAT Category CRUD operations"""
    __tablename__ = 'vat_category_change_requests'

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(20), nullable=False)  # 'create', 'update', 'delete'
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending', 'approved', 'rejected'

    # Reference to existing VAT category (for update/delete)
    vat_category_id = db.Column(db.Integer, db.ForeignKey('vat_categories.id'), nullable=True)

    # Proposed changes (JSON)
    proposed_data = db.Column(db.Text)  # JSON string

    # Approval workflow
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)

    # Reason for the change (provided by the requester, shown to reviewers)
    request_reason = db.Column(db.Text, nullable=True)

    # Relationships
    vat_category = db.relationship('VATCategory', backref='change_requests')
    requested_by = db.relationship('User', foreign_keys=[requested_by_id], backref='vat_category_requests')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id], backref='vat_category_reviews')

    def __repr__(self):
        return f'<VATCategoryChangeRequest {self.action} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'action': self.action,
            'status': self.status,
            'vat_category_id': self.vat_category_id,
            'proposed_data': self.proposed_data,
            'requested_by': self.requested_by.full_name if self.requested_by else None,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'reviewed_by': self.reviewed_by.full_name if self.reviewed_by else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'request_reason': self.request_reason,
        }
