"""True imprest petty cash (R-04 slice 4). Expenses book at REPLENISHMENT, not at
disbursement -- PettyCashVoucher is a held record with zero JE effect; only
PettyCashReplenishment touches the ledger."""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned


class PettyCashFund(db.Model):
    """Its own model -- NOT a BankAccount reuse; this has an active establish/
    adjust/close lifecycle a passive register doesn't. Still 1:1 with a GL account,
    same immutable-after-creation shape as BankAccount."""
    __tablename__ = 'petty_cash_funds'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False, unique=True)
    custodian = db.Column(db.String(200), nullable=True)
    float_amount = db.Column(db.Numeric(15, 2), nullable=False)
    funding_bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    account = db.relationship('Account')
    funding_bank_account = db.relationship('BankAccount')
    branch = db.relationship('Branch')
    # Reverse side of PettyCashVoucher.fund_id -- declared here (not as a second
    # independent relationship on PettyCashVoucher) so SQLAlchemy has exactly one
    # relationship/backref pair per FK.
    vouchers = db.relationship('PettyCashVoucher', foreign_keys='PettyCashVoucher.fund_id',
                               backref='fund', lazy='dynamic')


class PettyCashVoucher(db.Model):
    """A single disbursement, recorded as it happens. Posts NO JE -- status
    'held' until a PettyCashReplenishment books it."""
    __tablename__ = 'petty_cash_vouchers'

    id = db.Column(db.Integer, primary_key=True)
    fund_id = db.Column(db.Integer, db.ForeignKey('petty_cash_funds.id'), nullable=False, index=True)
    voucher_number = db.Column(db.String(50), unique=True, index=True, nullable=False)
    voucher_date = db.Column(db.Date, nullable=False)
    payee = db.Column(db.String(200), nullable=False)
    expense_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    receipt_ref = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='held', server_default='held')
    replenishment_id = db.Column(db.Integer, db.ForeignKey('petty_cash_replenishments.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    expense_account = db.relationship('Account')
    created_by = db.relationship('User')


class PettyCashReplenishment(RowVersioned, db.Model):
    """The JE-posting event. Groups held vouchers by expense account, folds in
    the physical count, and asserts the short/over plug (mirrors the payroll
    plug-guard discipline -- never silently absorbed)."""
    __tablename__ = 'petty_cash_replenishments'

    id = db.Column(db.Integer, primary_key=True)
    fund_id = db.Column(db.Integer, db.ForeignKey('petty_cash_funds.id'), nullable=False, index=True)
    replenishment_number = db.Column(db.String(50), unique=True, index=True, nullable=False)
    replenishment_date = db.Column(db.Date, nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=True)
    physical_cash_counted = db.Column(db.Numeric(15, 2), nullable=False)
    vouchers_total = db.Column(db.Numeric(15, 2), nullable=False)
    short_over_amount = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    replenish_amount = db.Column(db.Numeric(15, 2), nullable=False)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    fund_ref = db.relationship('PettyCashFund', foreign_keys=[fund_id])
    bank_account = db.relationship('BankAccount')
    journal_entry = db.relationship('JournalEntry')
    vouchers_replenished = db.relationship('PettyCashVoucher', backref='replenishment',
                                           foreign_keys=[PettyCashVoucher.replenishment_id])
