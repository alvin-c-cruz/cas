"""Seeds must never mint admin123.

Every seed path used to hardcode admin/admin123, and all four live instances were
first-run seeded that way. Now a freshly seeded admin gets a password from
CAS_SEED_ADMIN_PASSWORD (set it in a dev .env for a stable local value) or, absent
that, a random one printed once -- so no future/re-seeded/restored instance is born
on the default, and the login guard has nothing to force.
"""
import os

import pytest

from app.seeds.seed_data import resolve_seed_admin_password

pytestmark = [pytest.mark.unit, pytest.mark.security]


def test_env_override_is_honored(monkeypatch):
    monkeypatch.setenv('CAS_SEED_ADMIN_PASSWORD', 'Dev-Local#Chosen-2026')
    assert resolve_seed_admin_password() == 'Dev-Local#Chosen-2026'


def test_random_when_no_env(monkeypatch):
    monkeypatch.delenv('CAS_SEED_ADMIN_PASSWORD', raising=False)
    pw = resolve_seed_admin_password()
    assert pw and pw != 'admin123'
    assert len(pw) >= 16


def test_two_random_draws_differ(monkeypatch):
    monkeypatch.delenv('CAS_SEED_ADMIN_PASSWORD', raising=False)
    assert resolve_seed_admin_password() != resolve_seed_admin_password()


def test_seed_minimal_admin_is_not_default(db_session, monkeypatch, capsys):
    """The seeded admin must not carry admin123, and the password is printed once."""
    monkeypatch.setenv('CAS_SEED_ADMIN_PASSWORD', 'Seeded#Strong-2026')
    from app.seeds.seed_data import seed_minimal
    from app.users.models import User

    seed_minimal()

    admin = User.query.filter_by(username='admin').first()
    assert admin is not None
    assert not admin.check_password('admin123')
    assert admin.check_password('Seeded#Strong-2026')
    # The value is surfaced to the operator (so they can log in and rotate).
    assert 'Seeded#Strong-2026' in capsys.readouterr().out
