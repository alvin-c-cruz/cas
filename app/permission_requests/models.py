"""Permission Change Request model.

A Chief Accountant requests book_permissions additions for an accountant-role
target user; only admin may approve/reject. This is a request/approve seam
around the existing 2026-07-06 user-CRUD SoD boundary (project-chief-accountant-authz
memory), not a change to that boundary -- app/staff_management/scope.py and
app/users/views.py's /users/<id>/edit stay exactly as they are.
"""
import json
from app import db
from app.utils import ph_now


class PermissionChangeRequest(db.Model):
    __tablename__ = 'permission_change_requests'

    id = db.Column(db.Integer, primary_key=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_permissions = db.Column(db.Text, nullable=True)
    request_reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    target_user = db.relationship('User', foreign_keys=[target_user_id])
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    def get_requested_permissions(self):
        return json.loads(self.requested_permissions) if self.requested_permissions else {}

    def set_requested_permissions(self, perms_dict):
        self.requested_permissions = json.dumps(perms_dict)
