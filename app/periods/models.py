"""
Accounting Period models for period closing and locking.

Supports:
- Monthly period tracking
- Period closing by admin
- Lock past periods from editing
- Audit trail of closings/reopenings
"""
from app import db
from app.utils_helpers import ph_now
from datetime import datetime


class AccountingPeriod(db.Model):
    """
    Accounting Period model for tracking period status.

    Each period represents a calendar month. Once closed, transactions
    in that period cannot be created, edited, or deleted.
    """
    __tablename__ = 'accounting_periods'

    id = db.Column(db.Integer, primary_key=True)

    # Period identification
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)  # 1-12

    # Status: 'open', 'closed'
    status = db.Column(db.String(20), default='open', nullable=False, index=True)

    # Closing information
    closed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    closed_by = db.relationship('User', foreign_keys=[closed_by_id], backref='closed_periods')
    closed_at = db.Column(db.DateTime)

    # Optional notes/comments when closing
    notes = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)

    # Unique constraint: one record per year-month
    __table_args__ = (
        db.UniqueConstraint('year', 'month', name='unique_year_month'),
    )

    def __repr__(self):
        return f'<AccountingPeriod {self.year}-{self.month:02d} ({self.status})>'

    def get_period_name(self):
        """Get human-readable period name (e.g., 'January 2026')"""
        from datetime import date
        period_date = date(self.year, self.month, 1)
        return period_date.strftime('%B %Y')

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'year': self.year,
            'month': self.month,
            'period_name': self.get_period_name(),
            'status': self.status,
            'closed_by': self.closed_by.username if self.closed_by else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'notes': self.notes
        }

    @staticmethod
    def get_or_create_period(year, month):
        """
        Get existing period or create new one if it doesn't exist.

        Args:
            year: int - Year
            month: int - Month (1-12)

        Returns:
            AccountingPeriod instance
        """
        period = AccountingPeriod.query.filter_by(year=year, month=month).first()

        if not period:
            period = AccountingPeriod(
                year=year,
                month=month,
                status='open'
            )
            db.session.add(period)
            db.session.commit()

        return period

    @staticmethod
    def is_period_closed(year, month):
        """
        Check if a specific period is closed.

        Args:
            year: int - Year
            month: int - Month (1-12)

        Returns:
            bool - True if period is closed, False otherwise
        """
        period = AccountingPeriod.query.filter_by(year=year, month=month).first()
        return period.status == 'closed' if period else False

    def close_period(self, user, notes=None):
        """
        Close this accounting period.

        Args:
            user: User - User closing the period
            notes: str - Optional notes

        Returns:
            bool - True if successful
        """
        if self.status == 'closed':
            return False

        self.status = 'closed'
        self.closed_by = user
        self.closed_at = ph_now()
        self.notes = notes
        db.session.commit()

        return True

    def reopen_period(self):
        """
        Reopen a closed accounting period.

        Returns:
            bool - True if successful
        """
        if self.status == 'open':
            return False

        self.status = 'open'
        # Keep audit trail of who closed it
        db.session.commit()

        return True
