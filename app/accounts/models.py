from app import db
from app.utils import ph_now

class Account(db.Model):
    """Chart of Accounts model"""
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(200), unique=True, nullable=False)
    account_type = db.Column(db.String(20), nullable=False)  # Asset, Liability, Equity, Revenue, Expense
    classification = db.Column(db.String(20))  # Current, Non-Current
    normal_balance = db.Column(db.String(10), nullable=False)  # Debit, Credit
    parent_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=ph_now)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)

    # Relationship for hierarchical accounts
    children = db.relationship('Account', backref=db.backref('parent', remote_side=[id]))

    def __repr__(self):
        return f'<Account {self.code} - {self.name}>'

    def to_dict(self):
        """Convert account to dictionary"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'account_type': self.account_type,
            'classification': self.classification,
            'normal_balance': self.normal_balance,
            'parent_id': self.parent_id,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
