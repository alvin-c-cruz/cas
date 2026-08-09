"""DocumentRevision is append-only and unique per (document_type, document_id, revision_number)."""
import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.amendments.models import DocumentRevision


class TestDocumentRevisionModel:
    def test_stores_a_revision_row(self, db_session):
        rev = DocumentRevision(
            document_type='purchase_order', document_id=1, revision_number=0,
            snapshot_json='{"header": {}}', amended_by_id=None, branch_id=None,
        )
        db.session.add(rev)
        db.session.commit()

        saved = db.session.get(DocumentRevision, rev.id)
        assert saved.document_type == 'purchase_order'
        assert saved.revision_number == 0
        assert saved.amended_at is not None, 'amended_at must default, never be null'

    def test_revision_number_is_unique_per_document(self, db_session):
        for _ in range(2):
            db.session.add(DocumentRevision(
                document_type='purchase_order', document_id=7, revision_number=0,
                snapshot_json='{}',
            ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_same_revision_number_allowed_on_a_different_document_type(self, db_session):
        db.session.add(DocumentRevision(document_type='purchase_order', document_id=7,
                                        revision_number=0, snapshot_json='{}'))
        db.session.add(DocumentRevision(document_type='sales_invoice', document_id=7,
                                        revision_number=0, snapshot_json='{}'))
        db.session.commit()
        assert DocumentRevision.query.count() == 2
