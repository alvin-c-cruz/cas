"""Unit of Measure master (admin-managed reference data; per-company optional module)."""
from app import db
from app.utils import ph_now


class UnitOfMeasure(db.Model):
    __tablename__ = 'units_of_measure'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<UnitOfMeasure {self.code} - {self.name}>'

    def to_dict(self):
        return {'id': self.id, 'code': self.code, 'name': self.name,
                'is_active': self.is_active,
                'created_at': self.created_at.isoformat() if self.created_at else None}
