"""The two constraints that carry the design: one name per scope, one default per scope."""
import pytest
from sqlalchemy.exc import IntegrityError
from app import db
from app.print_layouts.models import PrintLayout

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _layout(name, is_default=False, scope_id=1):
    return PrintLayout(doc_type='purchase_orders', scope_id=scope_id, name=name,
                       payload='{}', is_default=is_default)


def test_two_layouts_cannot_share_a_name_in_one_scope(db_session):
    db_session.add(_layout('Purchasing - LX-310')); db_session.commit()
    db_session.add(_layout('Purchasing - LX-310'))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_the_same_name_is_fine_in_a_different_scope(db_session):
    db_session.add(_layout('Purchasing - LX-310', scope_id=1))
    db_session.add(_layout('Purchasing - LX-310', scope_id=2))
    db_session.commit()
    assert PrintLayout.query.count() == 2


def test_only_one_default_per_scope(db_session):
    """A partial unique index, not application code. Two defaults makes 'the default row'
    unanswerable and the answer varies by row order."""
    db_session.add(_layout('A', is_default=True)); db_session.commit()
    db_session.add(_layout('B', is_default=True))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_many_non_defaults_are_fine(db_session):
    db_session.add(_layout('A', is_default=True))
    db_session.add(_layout('B'))
    db_session.add(_layout('C'))
    db_session.commit()
    assert PrintLayout.query.count() == 3
