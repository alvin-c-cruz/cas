"""
Withholding Tax models for Philippine BIR compliance
"""
from app import db
from app.utils import ph_now

# BIR withholding regimes. 'expanded' (EWT) is creditable and flows to BIR 2307,
# the 1601-EQ QAP, and the SAWT. 'final' (FWT) is NOT creditable and belongs on
# BIR 2306 / 1601-FQ, neither of which is implemented -- see the R-08 spec.
TAX_TYPES = ('expanded', 'final')

# Human-readable label for each TAX_TYPES token. NOT NULL with only two values,
# so unlike PURCHASE_NATURE_LABELS this needs no '(unclassified)' /
# 'Unrecognized:' handling -- a plain dict lookup is enough.
TAX_TYPE_LABELS = {
    'expanded': 'Expanded (creditable)',
    'final': 'Final',
}


class WithholdingTax(db.Model):
    """Withholding Tax master table (shared across branches)"""
    __tablename__ = 'withholding_tax'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)  # e.g., WC010, WC011
    name = db.Column(db.String(100), nullable=False)
    # Seller/payee-POV name shown on sales documents (SI/CRV/customer). The
    # buyer-POV `name` stays for AP/CDV/vendor. Nullable + backfilled.
    sales_name = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text)
    rate = db.Column(db.Numeric(5, 2), nullable=False)  # e.g., 10.00 for 10%
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    tax_type = db.Column(db.String(10), nullable=False, default='expanded',
                         server_default='expanded')

    # Per-ATC GL account mapping (NULL falls back to the hardcoded anchors
    # 20301 / 10212 in the posting views).
    # payable side    -> APV/CDV (what we withhold from a vendor)
    # receivable side -> SI/CRV  (creditable WHT a customer withholds from us)
    payable_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    receivable_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    payable_account = db.relationship('Account', foreign_keys=[payable_account_id])
    receivable_account = db.relationship('Account', foreign_keys=[receivable_account_id])

    # Audit fields
    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='withholding_tax_created')
    updated_by = db.relationship('User', foreign_keys=[updated_by_id], backref='withholding_tax_updated')

    def __repr__(self):
        return f'<WithholdingTax {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'sales_name': self.sales_name,
            'description': self.description,
            'rate': float(self.rate) if self.rate else 0.0,
            'tax_type': self.tax_type,
            'is_active': self.is_active,
            'payable_account_id': self.payable_account_id,
            'payable_account_code': self.payable_account.code if self.payable_account else None,
            'receivable_account_id': self.receivable_account_id,
            'receivable_account_code': self.receivable_account.code if self.receivable_account else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WithholdingTaxChangeRequest(db.Model):
    """Change request table for Withholding Tax CRUD operations"""
    __tablename__ = 'withholding_tax_change_requests'

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(20), nullable=False)  # 'create', 'update', 'delete'
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending', 'approved', 'rejected'

    # Reference to existing withholding tax (for update/delete)
    withholding_tax_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)

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
    withholding_tax = db.relationship('WithholdingTax', backref='change_requests')
    requested_by = db.relationship('User', foreign_keys=[requested_by_id], backref='withholding_tax_requests')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id], backref='withholding_tax_reviews')

    def __repr__(self):
        return f'<WithholdingTaxChangeRequest {self.action} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'action': self.action,
            'status': self.status,
            'withholding_tax_id': self.withholding_tax_id,
            'proposed_data': self.proposed_data,
            'requested_by': self.requested_by.full_name if self.requested_by else None,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'reviewed_by': self.reviewed_by.full_name if self.reviewed_by else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'request_reason': self.request_reason,
        }
