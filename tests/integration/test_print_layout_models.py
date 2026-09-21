"""The two constraints that carry the design: one name per scope, one default per scope."""
import pytest
from sqlalchemy import text
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


def test_device_id_index_name_matches_the_migration(db_session):
    """The model must not rely on SQLAlchemy's index=True auto-naming for
    device_id: that would produce ix_named_print_layout_device_prefs_device_id
    (note the _id), while the migration's op.create_index() names it
    ix_named_print_layout_device_prefs_device (no _id). Two differently-named
    index objects for the same column would make a later `flask db migrate`
    propose dropping one and creating the other as pure churn.

    This asserts against the actual built schema (sqlite_master), not the
    model's metadata, because a metadata-only assertion would just restate
    __table_args__ and could never catch a create_all/migration name mismatch.
    """
    rows = db_session.execute(text(
        "select name from sqlite_master where type = 'index' "
        "and tbl_name = 'named_print_layout_device_prefs'"
    )).fetchall()
    index_names = {row[0] for row in rows}
    assert 'ix_named_print_layout_device_prefs_device' in index_names
    assert 'ix_named_print_layout_device_prefs_device_id' not in index_names
