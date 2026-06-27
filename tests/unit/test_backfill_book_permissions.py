import pytest
from app import db
from app.users.models import User
from app.users.migrations_support import backfill_book_permissions
from app.users.module_access import all_permission_keys

pytestmark = [pytest.mark.unit]


def _add(role, perms=None):
    u = User(username=f'{role}_bf', email=f'{role}_bf@t.com', full_name='BF', role=role, is_active=True)
    u.set_password('x')
    if perms is not None:
        u.set_book_permissions(perms)
    db.session.add(u)
    return u


def test_backfill_fills_empty_accountant_and_viewer(db_session):
    acct = _add('accountant')
    view = _add('viewer')
    db.session.commit()

    n = backfill_book_permissions(db.session)
    db.session.commit()

    assert n == 2
    assert set(acct.get_book_permissions().keys()) == set(all_permission_keys())
    assert all(acct.get_book_permissions().values())
    assert all(view.get_book_permissions().values())


def test_backfill_skips_admin_staff_and_already_configured(db_session):
    _add('admin')
    _add('staff')
    configured = _add('accountant', {'accounts_payable': True})  # already has one → skip
    db.session.commit()

    n = backfill_book_permissions(db.session)
    db.session.commit()

    assert n == 0
    assert configured.get_book_permissions() == {'accounts_payable': True}


def test_backfill_is_idempotent(db_session):
    _add('viewer')
    db.session.commit()
    assert backfill_book_permissions(db.session) == 1
    db.session.commit()
    assert backfill_book_permissions(db.session) == 0   # second run no-ops
