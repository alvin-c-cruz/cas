"""
Payroll Run document models: PayrollRun (header) + PayrollRunLine (per-employee).

Mirrors app/cash_disbursements/models.py's document+lifecycle pattern:
RowVersioned first base, draft->posted->voided/cancelled status column with
per-state actor/timestamp columns, header calculate_totals() summing lines,
line calculate_amounts() delegating to the pure calc engine (app.payroll.service).

Document numbering: `run_number` (PR-YYYY-MM-NNNN) is a column only here --
the generator function lands in a later task (worksheet slice).
"""
from decimal import Decimal

from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned


class PayrollRun(RowVersioned, db.Model):
    __tablename__ = 'payroll_runs'
    __table_args__ = (
        # Period-uniqueness: at most one non-voided run per branch/run_type/
        # pay_frequency/period among (year, month, semi_period) -- a voided or
        # cancelled run frees the slot for a fresh run of the same period.
        db.Index('uq_payroll_run_period',
                 'branch_id', 'run_type', 'pay_frequency',
                 'period_year', 'period_month', 'semi_period',
                 unique=True,
                 sqlite_where=db.text("status NOT IN ('voided', 'cancelled')")),
    )

    id = db.Column(db.Integer, primary_key=True)

    run_number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    run_type = db.Column(db.String(20), default='regular', nullable=False)   # regular/13th_month
    pay_frequency = db.Column(db.String(20), nullable=False)                 # monthly/semi_monthly/weekly/daily

    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)
    # 1 or 2 for a semi-monthly cutoff; 0 ("not applicable") for every other
    # pay_frequency. NOT NULL on purpose: SQLite (like every SQL engine) treats
    # NULL as distinct from NULL in a UNIQUE index, so two monthly runs for the
    # same period would BOTH have semi_period=NULL and the partial unique index
    # below would silently fail to catch the duplicate -- proven by running the
    # partial-index test with a nullable column (it did not raise). 0 is a real,
    # comparable value, so the index works uniformly across all frequencies.
    semi_period = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    pay_date = db.Column(db.Date, nullable=False)

    # Snapshot of the payroll_semi_monthly_timing setting, read by
    # PayrollRunLine.calculate_amounts() via compute_line's semi_timing input.
    semi_timing = db.Column(db.String(20), nullable=True)   # second_cutoff/split_50_50/first_cutoff

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    # Computed total buckets (calculate_totals() sums these across lines)
    total_gross = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_taxable = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_nontax = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_sss_ee = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_sss_er = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_sss_ec = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_philhealth_ee = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_philhealth_er = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_pagibig_ee = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_pagibig_er = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_wht = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_sss_loan = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_pagibig_loan = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_thirteenth_month = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_net_pay = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_payroll_runs')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_payroll_runs')
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_payroll_runs')

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    voided_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    void_reason = db.Column(db.String(255))
    cancel_reason = db.Column(db.String(500))

    lines = db.relationship('PayrollRunLine', backref='run', lazy='select',
                            cascade='all, delete-orphan',
                            order_by='PayrollRunLine.line_number')

    def __repr__(self):
        return f'<PayrollRun {self.run_number}>'

    def calculate_totals(self):
        def _sum(attr):
            return sum(
                (Decimal(str(getattr(l, attr) or 0)) for l in self.lines),
                Decimal('0.00')
            )
        self.total_gross = _sum('gross_pay')
        self.total_taxable = _sum('taxable_comp')
        self.total_nontax = _sum('nontax_allowance')
        self.total_sss_ee = _sum('sss_ee')
        self.total_sss_er = _sum('sss_er')
        self.total_sss_ec = _sum('sss_ec')
        self.total_philhealth_ee = _sum('philhealth_ee')
        self.total_philhealth_er = _sum('philhealth_er')
        self.total_pagibig_ee = _sum('pagibig_ee')
        self.total_pagibig_er = _sum('pagibig_er')
        self.total_wht = _sum('wht')
        self.total_sss_loan = _sum('sss_loan')
        self.total_pagibig_loan = _sum('pagibig_loan')
        self.total_thirteenth_month = _sum('thirteenth_month')
        self.total_net_pay = _sum('net_pay')

    def to_dict(self):
        return {
            'id': self.id,
            'run_number': self.run_number,
            'branch_id': self.branch_id,
            'run_type': self.run_type,
            'pay_frequency': self.pay_frequency,
            'period_year': self.period_year,
            'period_month': self.period_month,
            'semi_period': self.semi_period,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'pay_date': self.pay_date.isoformat() if self.pay_date else None,
            'status': self.status,
            'total_gross': float(self.total_gross),
            'total_wht': float(self.total_wht),
            'total_net_pay': float(self.total_net_pay),
        }


class PayrollRunLine(db.Model):
    __tablename__ = 'payroll_run_lines'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    employee = db.relationship('Employee', foreign_keys=[employee_id])

    # Snapshots (captured from Employee when the line is added -- a later
    # change to the employee master must not silently reshape a saved run)
    employee_name = db.Column(db.String(200), nullable=False)
    pay_basis = db.Column(db.String(20), nullable=False)          # monthly/daily
    rate = db.Column(db.Numeric(12, 2), default=0, nullable=False)   # basic monthly or daily rate
    tax_status_code = db.Column(db.String(10))
    is_mwe = db.Column(db.Boolean, default=False, nullable=False)

    # Entered inputs
    days = db.Column(db.Numeric(6, 2), default=0, nullable=False)
    hours = db.Column(db.Numeric(6, 2), default=0, nullable=False)
    ot_pay = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    holiday_pay = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    taxable_allowance = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    nontax_allowance = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    # Computed (calculate_amounts() writes these from service.compute_line)
    basic_gross = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    gross_pay = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    sss_msc = db.Column(db.Numeric(15, 2), nullable=True)
    sss_ee = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    sss_er = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    sss_ec = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    philhealth_ee = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    philhealth_er = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    pagibig_ee = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    pagibig_er = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    taxable_comp = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    wht = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    wht_bracket_id = db.Column(db.Integer, db.ForeignKey('compensation_wht_brackets.id'), nullable=True)

    # P3 (loans/13th-month) -- columns land now so this migration runs once;
    # always 0 until Tasks 11/13 wire the actual deduction/aggregation.
    sss_loan = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    pagibig_loan = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    thirteenth_month = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    net_pay = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    def __repr__(self):
        return f'<PayrollRunLine run={self.run_id} employee={self.employee_name}>'

    def calculate_amounts(self):
        # Imported lazily to avoid a module-load-order edge with app.payroll.service
        # (service.py has no dependency on models.py, but keeping the import local
        # here mirrors how other document models keep their service imports scoped).
        from app.payroll import service

        inputs = {
            'pay_basis': self.pay_basis,
            'monthly_rate': self.rate,
            'daily_rate': self.rate,
            'days': self.days,
            'hours': self.hours,
            'ot_pay': self.ot_pay,
            'holiday_pay': self.holiday_pay,
            'taxable_allowance': self.taxable_allowance,
            'nontax_allowance': self.nontax_allowance,
            'is_mwe': self.is_mwe,
            'pay_frequency': self.run.pay_frequency,
            'period_end': self.run.period_end,
            'semi_timing': self.run.semi_timing,
            'semi_period': self.run.semi_period,
        }
        result = service.compute_line(inputs)

        self.basic_gross = result['basic_gross']
        self.gross_pay = result['gross_pay']
        st = result['statutory']
        self.sss_msc = st['sss_msc']
        self.sss_ee = st['sss_ee']
        self.sss_er = st['sss_er']
        self.sss_ec = st['sss_ec']
        self.philhealth_ee = st['philhealth_ee']
        self.philhealth_er = st['philhealth_er']
        self.pagibig_ee = st['pagibig_ee']
        self.pagibig_er = st['pagibig_er']
        self.taxable_comp = result['taxable_comp']
        self.wht = result['wht']
        self.wht_bracket_id = result['wht_bracket_id']
        self.net_pay = result['net_pay']

    def to_dict(self):
        return {
            'id': self.id,
            'line_number': self.line_number,
            'employee_id': self.employee_id,
            'employee_name': self.employee_name,
            'pay_basis': self.pay_basis,
            'rate': float(self.rate),
            'is_mwe': self.is_mwe,
            'days': float(self.days) if self.days is not None else None,
            'hours': float(self.hours) if self.hours is not None else None,
            'ot_pay': float(self.ot_pay),
            'holiday_pay': float(self.holiday_pay),
            'taxable_allowance': float(self.taxable_allowance),
            'nontax_allowance': float(self.nontax_allowance),
            'basic_gross': float(self.basic_gross),
            'gross_pay': float(self.gross_pay),
            'taxable_comp': float(self.taxable_comp),
            'wht': float(self.wht),
            'net_pay': float(self.net_pay),
        }
