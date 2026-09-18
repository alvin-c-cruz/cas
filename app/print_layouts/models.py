"""Named pre-printed layouts, and which layout each workstation prints with.

Configuration, not transactions — which is why neither table carries `branch_id`.
The branch IS `scope_id`, generalised so cd_check can later scope by cash account
without a schema change.

`scope_id` is NOT NULL with 0 meaning unscoped: SQLite treats NULLs as distinct in
a UNIQUE constraint, so a nullable column would let two rows share
(doc_type, NULL, 'Default') and defeat the uniqueness silently.
"""
from app import db
from app.utils import ph_now


class PrintLayout(db.Model):
    __tablename__ = 'named_print_layouts'
    __table_args__ = (
        db.UniqueConstraint('doc_type', 'scope_id', 'name', name='uq_named_print_layouts_name'),
        # Partial unique index: at most one default per scope. Enforced by the
        # database because resolution asks for "the default row" and two of them
        # would resolve by row order.
        db.Index('uq_named_print_layouts_one_default', 'doc_type', 'scope_id',
                 unique=True, sqlite_where=db.text('is_default = 1')),
    )

    id = db.Column(db.Integer, primary_key=True)
    doc_type = db.Column(db.String(40), nullable=False, index=True)
    scope_id = db.Column(db.Integer, nullable=False, default=0)
    name = db.Column(db.String(100), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=ph_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=ph_now, onupdate=ph_now)

    def __repr__(self):
        return f'<PrintLayout {self.doc_type}/{self.scope_id} {self.name!r}>'


class PrintLayoutDevicePref(db.Model):
    """Which layout ONE WORKSTATION prints with. Deliberately no user_id: a layout
    belongs to a printer, and a workstation prints to one printer, so the machine's
    choice is the right answer for whoever sits at it."""
    __tablename__ = 'named_print_layout_device_prefs'
    __table_args__ = (
        db.UniqueConstraint('device_id', 'doc_type', 'scope_id',
                            name='uq_named_print_layout_device_prefs'),
    )

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), nullable=False, index=True)
    doc_type = db.Column(db.String(40), nullable=False)
    scope_id = db.Column(db.Integer, nullable=False, default=0)
    # SET NULL, never CASCADE: deleting a layout must strand the workstation on the
    # default, not delete the workstation's row.
    layout_id = db.Column(db.Integer, db.ForeignKey('named_print_layouts.id', ondelete='SET NULL'),
                          nullable=True)
    label = db.Column(db.String(100), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=ph_now, onupdate=ph_now)

    layout = db.relationship('PrintLayout')
