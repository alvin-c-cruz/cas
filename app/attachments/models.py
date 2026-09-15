"""Shared file attachments for PR, PO, RR and CDV.

One polymorphic table keyed by (document_type, document_id), the shape
DocumentRevision already uses for the same documents. AP and Sales Invoice keep
their own older per-module tables (accounts_payable_attachments,
sales_invoice_attachments); folding them in is a separate data migration.

Files live at instance/uploads/<document_type>/<document_id>/<stored_filename>.

No branch_id: an attachment is evidence belonging to its parent document and
takes the parent's branch, exactly like AccountsPayableAttachment.
"""
from app import db
from app.utils import ph_now


class DocumentAttachment(db.Model):
    __tablename__ = 'document_attachments'
    __table_args__ = (
        db.Index('ix_document_attachments_doc', 'document_type', 'document_id'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Matches the module's audit `module` name, e.g. 'purchase_orders'.
    document_type = db.Column(db.String(40), nullable=False)

    # PLAIN Integer, no ORM FK: points at four different tables.
    document_id = db.Column(db.Integer, nullable=False)

    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)  # uuid4 hex + ext
    mime_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # bytes

    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_id])
    uploaded_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    def __repr__(self):
        return (f'<DocumentAttachment {self.original_filename} '
                f'{self.document_type}={self.document_id}>')

    @property
    def is_image(self):
        return self.mime_type.startswith('image/')

    @property
    def is_pdf(self):
        return self.mime_type == 'application/pdf'

    @property
    def is_previewable(self):
        """Can this render inline in the popup? Images and PDFs can; Office
        documents cannot be shown in a browser frame and stay download-only."""
        return self.is_image or self.is_pdf

    @property
    def file_size_human(self):
        if self.file_size < 1024:
            return f'{self.file_size} B'
        if self.file_size < 1024 * 1024:
            return f'{self.file_size / 1024:.1f} KB'
        return f'{self.file_size / (1024 * 1024):.1f} MB'
