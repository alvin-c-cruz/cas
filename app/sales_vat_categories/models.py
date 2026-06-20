"""
Sales VAT Category models (output/sales side) for Philippine BIR compliance.
Purchase-side categories live in app.vat_categories (VATCategory).
"""
from app import db
from app.utils import ph_now


class SalesVATCategory(db.Model):
    """Sales (output) VAT Category master table (shared across branches)."""
    __tablename__ = 'sales_vat_categories'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    rate = db.Column(db.Numeric(5, 2), nullable=False)  # e.g., 12.00 for 12%
    # BIR sales classifier: regular / zero_export / zero_other / exempt / government
    transaction_nature = db.Column(db.String(30), nullable=False, default='regular')
    # Output VAT account used for sales journal entries. NULL is correct for
    # zero-rate/exempt categories; the form requires it when rate > 0.
    output_vat_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'),
                                      nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_by = db.relationship('User', foreign_keys=[created_by_id],
                                 backref='sales_vat_categories_created')
    updated_by = db.relationship('User', foreign_keys=[updated_by_id],
                                 backref='sales_vat_categories_updated')
    output_vat_account = db.relationship('Account', foreign_keys=[output_vat_account_id])

    def __repr__(self):
        return f'<SalesVATCategory {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'rate': float(self.rate) if self.rate else 0.0,
            'transaction_nature': self.transaction_nature,
            'output_vat_account_id': self.output_vat_account_id,
            'output_vat_account_code': self.output_vat_account.code if self.output_vat_account else None,
            'output_vat_account_name': self.output_vat_account.name if self.output_vat_account else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SalesVATCategoryChangeRequest(db.Model):
    """Change request table for Sales VAT Category CRUD operations."""
    __tablename__ = 'sales_vat_category_change_requests'

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(20), nullable=False)   # 'create', 'update', 'delete'
    status = db.Column(db.String(20), default='pending', nullable=False)

    sales_vat_category_id = db.Column(db.Integer,
                                      db.ForeignKey('sales_vat_categories.id'),
                                      nullable=True)
    proposed_data = db.Column(db.Text)  # JSON string

    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
    request_reason = db.Column(db.Text, nullable=True)

    sales_vat_category = db.relationship('SalesVATCategory', backref='change_requests')
    requested_by = db.relationship('User', foreign_keys=[requested_by_id],
                                   backref='sales_vat_category_requests')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id],
                                  backref='sales_vat_category_reviews')

    def __repr__(self):
        return f'<SalesVATCategoryChangeRequest {self.action} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'action': self.action,
            'status': self.status,
            'sales_vat_category_id': self.sales_vat_category_id,
            'proposed_data': self.proposed_data,
            'requested_by': self.requested_by.full_name if self.requested_by else None,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'reviewed_by': self.reviewed_by.full_name if self.reviewed_by else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'request_reason': self.request_reason,
        }
