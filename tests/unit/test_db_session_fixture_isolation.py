"""Regression guard for tests/conftest.py's db_session fixture (delete-all-
rows-at-teardown isolation). Two tests create a User with the identical
username; if a future change to db_session breaks isolation, the second
insert raises a UNIQUE constraint violation on `username`.

Originally written against local throwaway fixtures to prove the mechanism
before the real fixture existed (see git history) -- now exercises the real
db_session fixture directly, so it stays a live guard against regressions.
"""
from app.users.models import User
from app.branches.models import Branch


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


def test_isolation_canary_one_same_username(db_session):
    _make_isolation_user(db_session, 'fixture_isolation_canary')
    assert User.query.filter_by(username='fixture_isolation_canary').count() == 1


def test_isolation_canary_two_same_username(db_session):
    """Would raise sqlite3.IntegrityError: UNIQUE constraint failed on
    `username` if the previous test's row survived into this one -- proving
    the delete-all-rows teardown actually isolates tests."""
    _make_isolation_user(db_session, 'fixture_isolation_canary')
    assert User.query.filter_by(username='fixture_isolation_canary').count() == 1


def test_isolation_canary_fk_linked_rows_wipe_cleanly(db_session):
    """Same proof for an FK-linked pair (Branch <- User.branch_id) -- confirms
    the per-table delete loop needs no FK-order care (SQLite FK enforcement is
    OFF app-wide; memory sqlite-fk-off-delete-guard)."""
    branch = Branch(code='ISOB', name='Isolation Branch', is_active=True)
    db_session.add(branch)
    db_session.commit()
    user = User(
        username='fixture_isolation_fk_user',
        email='fixture_isolation_fk_user@test.com',
        full_name='Isolation FK Canary',
        role='staff',
        is_active=True,
        branch_id=branch.id,
    )
    user.set_password('canary123')
    db_session.add(user)
    db_session.commit()
    assert User.query.filter_by(username='fixture_isolation_fk_user').count() == 1
