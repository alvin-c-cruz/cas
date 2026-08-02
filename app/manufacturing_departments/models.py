"""Manufacturing Department master (R-07 Process Track slice P1) -- the cost pool
that process-mode production accumulates against over a period, the counterpart to
the Discrete track's WorkCenter.

Branch-scoped, mirrors the work_centers / units_of_measure master-data shape (no
RowVersioned -- simple reference data, not a concurrently-edited document).

Deliberately has NO hourly_rate, which is where it diverges from WorkCenter:
process mode allocates conversion cost (labor + overhead) to the department for a
period through R-03a's existing ExpenseAllocationRule driver rather than an hourly
rate. See docs/superpowers/specs/2026-07-19-manufacturing-r07-design.md, Process
Track section.
"""
from app import db
from app.utils import ph_now


class ManufacturingDepartment(db.Model):
    __tablename__ = 'manufacturing_departments'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    branch = db.relationship('Branch')
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<ManufacturingDepartment {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id, 'branch_id': self.branch_id, 'code': self.code,
            'name': self.name, 'is_active': self.is_active,
        }
