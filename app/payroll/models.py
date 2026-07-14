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

    # Task 11: which specific EmployeeLoan record (if any) this line's
    # sss_loan/pagibig_loan amount was drawn against. Recorded at
    # calculate_amounts() time (whenever the employee's ACTIVE loan of that
    # type is looked up), NOT just the amount -- a correct reversal on cancel
    # needs to credit the EXACT loan record that was debited at post, not
    # "whichever loan is currently active for this employee" (which could
    # have changed between post and cancel). Plain nullable Integer, no
    # inline FK (SQLite batch add_column can't carry one -- see CLAUDE.md's
    # "Batch add_column cannot carry an inline sa.ForeignKey" gotcha); the
    # ORM relationship below still gives FK-shaped joins.
    sss_loan_id = db.Column(db.Integer, db.ForeignKey('employee_loans.id'), nullable=True)
    pagibig_loan_id = db.Column(db.Integer, db.ForeignKey('employee_loans.id'), nullable=True)

    # sss_loan/pagibig_loan: the amount ACTUALLY applied on this line, already
    # capped at min(monthly_amortization, balance) by compute_line -- this is
    # both what calculate_totals() sums into the run's total_sss_loan/
    # total_pagibig_loan header buckets (post_payroll_je's 20405/20406 credit
    # legs) AND the exact figure apply_loan_balances()/restore_loan_balances()
    # decrement/restore against the referenced loan -- never recomputed fresh
    # at post or cancel time, so a monthly_amortization edit in between can't
    # cause the reversal to drift from what was actually decremented.
    sss_loan = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    pagibig_loan = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    # P3 (13th-month, Task 13): for a run_type='13th_month' line, this is
    # EITHER the auto-aggregated YTD-basic/12 value (service.
    # compute_thirteenth_month, written by calculate_amounts() whenever
    # thirteenth_month_override is False) OR a manually-entered final amount
    # that calculate_amounts() leaves untouched when thirteenth_month_override
    # is True -- mirrors sales_invoices/accounts_payable's vat_override/
    # wt_override convention: a bool flag sitting next to the single amount
    # column it gates, not a separate shadow "manual value" column. Always
    # 0.00 for a run_type='regular' line (calculate_amounts() never touches
    # it on that path).
    thirteenth_month = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    thirteenth_month_override = db.Column(db.Boolean, default=False, nullable=False,
                                          server_default='0')

    net_pay = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    def __repr__(self):
        return f'<PayrollRunLine run={self.run_id} employee={self.employee_name}>'

    def calculate_amounts(self):
        # Imported lazily to avoid a module-load-order edge with app.payroll.service
        # (service.py has no dependency on models.py, but keeping the import local
        # here mirrors how other document models keep their service imports scoped).
        from app.payroll import service

        # Task 13: a run_type='13th_month' line is a completely separate calc
        # path -- no statutory, no loans, WHT only on the excess over
        # service.THIRTEENTH_MONTH_EXEMPTION. Branch out before any of the
        # regular-run (compute_line) machinery below runs.
        if self.run.run_type == '13th_month':
            self._calculate_thirteenth_month_amounts(service)
            return

        # Task 11: look up the employee's ACTIVE loan of each type (at most one,
        # per the uq_employee_loan_active_per_type partial unique index) fresh on
        # every calculate_amounts() call -- this runs on every draft save/edit
        # (create_run/edit_run POST), not just once, so it always reflects the
        # loan's CURRENT balance, not a stale snapshot from an earlier edit. The
        # FK is recorded now so a later post/cancel applies/restores against
        # THIS specific loan record, not "whichever loan is active at that time".
        sss_loan = EmployeeLoan.query.filter_by(
            employee_id=self.employee_id, loan_type='sss', status='active').first()
        pagibig_loan = EmployeeLoan.query.filter_by(
            employee_id=self.employee_id, loan_type='pagibig', status='active').first()
        self.sss_loan_id = sss_loan.id if sss_loan else None
        self.pagibig_loan_id = pagibig_loan.id if pagibig_loan else None

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
            'sss_loan_amortization': sss_loan.monthly_amortization if sss_loan else 0,
            'sss_loan_balance': sss_loan.balance if sss_loan else 0,
            'pagibig_loan_amortization': pagibig_loan.monthly_amortization if pagibig_loan else 0,
            'pagibig_loan_balance': pagibig_loan.balance if pagibig_loan else 0,
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
        self.sss_loan = result['sss_loan']
        self.pagibig_loan = result['pagibig_loan']
        self.net_pay = result['net_pay']

    def _calculate_thirteenth_month_amounts(self, service):
        """Task 13 calc path for a run_type='13th_month' line: no statutory,
        no loans; WHT only on the excess over service.THIRTEENTH_MONTH_EXEMPTION
        (see service.compute_thirteenth_month_line's docstring for the
        WHT-on-excess design reasoning).

        The final amount is either the auto-aggregated YTD-basic/12 value
        (service.compute_thirteenth_month, written into self.thirteenth_month
        here) or, when thirteenth_month_override is True, whatever value the
        caller already placed in self.thirteenth_month BEFORE calling
        calculate_amounts() -- that value is read back untouched, never
        recomputed, exactly mirroring how vat_override/wt_override guard
        vat_amount/withholding_tax_amount on SalesInvoice/AccountsPayableBill.

        Every statutory and loan field is explicitly zeroed (not merely left
        at its prior value) so a line that is EDITED from 'regular' inputs
        into a 13th-month line (or re-saved) never carries forward stale
        SSS/PhilHealth/Pag-IBIG/loan amounts from an earlier calculation.
        """
        if self.thirteenth_month_override:
            amount = Decimal(self.thirteenth_month or 0)
        else:
            amount = service.compute_thirteenth_month(self.employee, self.run.period_year)
            self.thirteenth_month = amount

        result = service.compute_thirteenth_month_line(amount, self.run.period_end)

        self.basic_gross = result['gross_pay']
        self.gross_pay = result['gross_pay']
        self.sss_msc = None
        self.sss_ee = Decimal('0.00')
        self.sss_er = Decimal('0.00')
        self.sss_ec = Decimal('0.00')
        self.philhealth_ee = Decimal('0.00')
        self.philhealth_er = Decimal('0.00')
        self.pagibig_ee = Decimal('0.00')
        self.pagibig_er = Decimal('0.00')
        self.taxable_comp = result['taxable_comp']
        self.wht = result['wht']
        self.wht_bracket_id = result['wht_bracket_id']
        self.sss_loan_id = None
        self.pagibig_loan_id = None
        self.sss_loan = Decimal('0.00')
        self.pagibig_loan = Decimal('0.00')
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
            'sss_loan': float(self.sss_loan),
            'pagibig_loan': float(self.pagibig_loan),
            'net_pay': float(self.net_pay),
        }


class EmployeeLoan(db.Model):
    """SSS/Pag-IBIG salary-loan amortization schedule for one employee.

    Task 11 (R-06 Payroll v1, P3 slice): a payroll line's calculate_amounts()
    looks up the employee's ACTIVE loan of each type (at most one per type,
    enforced by the partial unique index below) and deducts
    min(monthly_amortization, balance) via app.payroll.service.compute_line.
    `balance` is mutated ONLY by the payroll-run lifecycle (post decrements it,
    cancel restores it exactly -- see service.apply_loan_balances/
    restore_loan_balances) -- never edited directly by this task (the loan
    editor UI that lets an accountant create/adjust a loan record is Task 12's
    job, out of scope here).

    status: 'active' (eligible for auto-deduction), 'paid' (balance reached
    zero -- informational; nothing in this task auto-transitions a loan into
    this state, left for Task 12's editor to manage explicitly), 'cancelled'
    (the loan was written off/voided outside payroll and must stop deducting
    without needing its balance zeroed first). Only 'active' loans are picked
    up by calculate_amounts()'s lookup.

    NOT RowVersioned: every mutation to `balance` in this task's scope
    (post_run/cancel_run) already runs inside PayrollRun's own claim_version-
    locked transaction, and the balance write itself uses an atomic SQL-side
    UPDATE (balance = balance +/- amount), not a Python read-modify-write --
    see apply_loan_balances()'s docstring for why that closes the classic
    lost-update race for THIS task's mutation paths. A future loan-editor UI
    (Task 12) that lets a user directly edit principal/monthly_amortization/
    balance would be a genuinely NEW concurrent-write surface this class
    doesn't yet have, and should reconsider RowVersioned at that point.
    """
    __tablename__ = 'employee_loans'
    __table_args__ = (
        # At most one ACTIVE loan per (employee, loan_type) -- calculate_amounts()
        # resolves "the" active loan via a plain filter_by(...).first(), and this
        # partial unique index (mirrors payroll_runs' own period-uniqueness
        # pattern) makes that lookup well-defined instead of silently picking an
        # arbitrary row among several concurrently-active loans of the same type.
        db.Index('uq_employee_loan_active_per_type', 'employee_id', 'loan_type',
                 unique=True, sqlite_where=db.text("status = 'active'")),
    )

    id = db.Column(db.Integer, primary_key=True)

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    employee = db.relationship('Employee', foreign_keys=[employee_id])

    loan_type = db.Column(db.String(20), nullable=False)   # 'sss' / 'pagibig'
    principal = db.Column(db.Numeric(12, 2), nullable=False)
    monthly_amortization = db.Column(db.Numeric(12, 2), nullable=False)
    balance = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), default='active', nullable=False, index=True)   # active/paid/cancelled

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    def __repr__(self):
        return f'<EmployeeLoan {self.loan_type} employee={self.employee_id} balance={self.balance}>'

    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'loan_type': self.loan_type,
            'principal': float(self.principal),
            'monthly_amortization': float(self.monthly_amortization),
            'balance': float(self.balance),
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
