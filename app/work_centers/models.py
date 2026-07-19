"""Work Center master (R-07 Discrete Track slice D1) -- the resource/machine/
labor pool a routing operation runs at. Branch-scoped, mirrors the
units_of_measure master-data shape (no RowVersioned -- simple reference data,
not a concurrently-edited document)."""
from app import db
from app.utils import ph_now


class WorkCenter(db.Model):
    __tablename__ = 'work_centers'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    hourly_rate = db.Column(db.Numeric(15, 2), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    branch = db.relationship('Branch')
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<WorkCenter {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id, 'branch_id': self.branch_id, 'code': self.code, 'name': self.name,
            'hourly_rate': float(self.hourly_rate) if self.hourly_rate is not None else None,
            'is_active': self.is_active,
        }
