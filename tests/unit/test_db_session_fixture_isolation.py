"""Proves the delete-all-rows-between-tests isolation mechanism works against
this app's real Flask-SQLAlchemy/SQLite StaticPool setup, before the real
db_session fixture in tests/conftest.py is touched.

These local fixtures (canary_schema, canary_session) are throwaway -- Task 2
of the fixture-scope-speedup plan rewrites this file to use the real
db_session fixture once it has been swapped to the same mechanism, at which
point this becomes a permanent regression guard instead of a one-off proof.
"""
import pytest

from app import db
from app.users.models import User
from app.branches.models import Branch


@pytest.fixture(scope='session')
def canary_schema(app):
    with app.app_context():
        db.create_all()
        yield
        db.drop_all()


@pytest.fixture(scope='function')
def canary_session(app, canary_schema):
    with app.app_context():
        yield db.session

        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        db.session.remove()


def _make_isolation_user(session, username):
    user = User(
        username=username,
        email=f'{username}@test.com',
        full_name='Isolation Canary',
        role='staff',
        is_active=True,
    )
    user.set_password('canary123')
    session.add(user)
    session.commit()
    return user


def test_isolation_canary_one_same_username(canary_session):
    _make_isolation_user(canary_session, 'fixture_isolation_canary')
    assert User.query.filter_by(username='fixture_isolation_canary').count() == 1


def test_isolation_canary_two_same_username(canary_session):
    """Would raise sqlite3.IntegrityError: UNIQUE constraint failed on
    `username` if the previous test's row survived into this one -- proving
    the delete-all-rows teardown actually isolates tests."""
    _make_isolation_user(canary_session, 'fixture_isolation_canary')
    assert User.query.filter_by(username='fixture_isolation_canary').count() == 1


def test_isolation_canary_fk_linked_rows_wipe_cleanly(canary_session):
    """Same proof for an FK-linked pair (Branch <- User.branch_id) -- confirms
    the per-table delete loop needs no FK-order care (SQLite FK enforcement is
    OFF app-wide; memory sqlite-fk-off-delete-guard)."""
    branch = Branch(code='ISOB', name='Isolation Branch', is_active=True)
    canary_session.add(branch)
    canary_session.commit()
    user = User(
        username='fixture_isolation_fk_user',
        email='fixture_isolation_fk_user@test.com',
        full_name='Isolation FK Canary',
        role='staff',
        is_active=True,
        branch_id=branch.id,
    )
    user.set_password('canary123')
    canary_session.add(user)
    canary_session.commit()
    assert User.query.filter_by(username='fixture_isolation_fk_user').count() == 1
