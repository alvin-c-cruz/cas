"""Employee master (payroll foundation). Branch-scoped, opt-in module."""
from app import db
from app.utils import ph_now


class Employee(db.Model):
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)

    # Identity
    employee_no = db.Column(db.String(20), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100), nullable=False)
    birthdate = db.Column(db.Date)
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))

    # Government IDs
    tin = db.Column(db.String(50))
    sss_no = db.Column(db.String(50))
    philhealth_no = db.Column(db.String(50))
    pagibig_no = db.Column(db.String(50))

    # Employment
    date_hired = db.Column(db.Date)
    employment_status = db.Column(db.String(30))   # regular/probationary/contractual/part-time
    position = db.Column(db.String(120))           # free-form HR title; NOT a user role

    # Branch scope (branch-scoping rule)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    # Tax
    tax_status_code = db.Column(db.String(10))
    qualified_dependents = db.Column(db.Integer, default=0)
    is_minimum_wage = db.Column(db.Boolean, default=False)

    # Compensation
    pay_basis = db.Column(db.String(20))           # monthly/daily
    basic_rate = db.Column(db.Numeric(12, 2))
    pay_frequency = db.Column(db.String(20))       # monthly/semi-monthly

    # Optional identity link to a login (pure identity mapping; no role/position meaning)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    user = db.relationship('User', foreign_keys=[user_id])

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Eligible to be credited as the salesperson on sales documents (capability, not a title).
    is_salesperson = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    def __repr__(self):
        return f'<Employee {self.employee_no} - {self.full_name}>'

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return ' '.join(p for p in parts if p)

    def to_dict(self):
        return {
            'id': self.id,
            'employee_no': self.employee_no,
            'first_name': self.first_name,
            'middle_name': self.middle_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'birthdate': self.birthdate.isoformat() if self.birthdate else None,
            'address': self.address,
            'phone': self.phone,
            'email': self.email,
            'tin': self.tin,
            'sss_no': self.sss_no,
            'philhealth_no': self.philhealth_no,
            'pagibig_no': self.pagibig_no,
            'date_hired': self.date_hired.isoformat() if self.date_hired else None,
            'employment_status': self.employment_status,
            'position': self.position,
            'branch_id': self.branch_id,
            'tax_status_code': self.tax_status_code,
            'qualified_dependents': self.qualified_dependents,
            'is_minimum_wage': self.is_minimum_wage,
            'pay_basis': self.pay_basis,
            'basic_rate': float(self.basic_rate) if self.basic_rate is not None else None,
            'pay_frequency': self.pay_frequency,
            'user_id': self.user_id,
            'is_active': self.is_active,
            'is_salesperson': self.is_salesperson,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
