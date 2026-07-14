import pytest
from app import db
from app.users.models import User
from app.opening_balances.approval_models import OpeningBalanceChangeRequest


def _user(username, role):
    u = User(username=username, email=f'{username}@t.co', full_name=username.title(),
              role=role, is_active=True)
    u.set_password('Passw0rd!')
    db.session.add(u); db.session.commit()
    return u


def _req(by):
    r = OpeningBalanceChangeRequest(branch_id=1, requested_by=by)
    r.set_change_data({'cutover_date': '2026-01-01', 'lines': []})
    db.session.add(r); db.session.commit()
    return r


@pytest.mark.unit
class TestOpeningBalanceApprovalMatrix:
    def test_sole_accountant_auto_approves(self, db_session):
        _user('acc', 'accountant')
        assert _req('acc').auto_approves() is True

    def test_sole_ca_auto_approves(self, db_session):
        _user('ca', 'chief_accountant')
        assert _req('ca').auto_approves() is True

    def test_lone_accountant_auto_even_with_admin_present(self, db_session):
        _user('acc', 'accountant'); _user('boss', 'admin')
        assert _req('acc').auto_approves() is True   # admin not counted in A

    def test_admin_with_accountant_present_is_pending(self, db_session):
        _user('acc', 'accountant'); _user('boss', 'admin')
        assert _req('boss').auto_approves() is False

    def test_both_present_no_auto(self, db_session):
        _user('acc', 'accountant'); _user('ca', 'chief_accountant')
        assert _req('acc').auto_approves() is False
        assert _req('ca').auto_approves() is False

    def test_zero_accountants_admin_solo_fallback(self, db_session):
        _user('boss', 'admin')
        assert _req('boss').auto_approves() is True

    def test_can_be_approved_by_peer_yes_self_no(self, db_session):
        _user('acc', 'accountant'); _user('ca', 'chief_accountant'); _user('boss', 'admin')
        r = _req('acc')   # both present -> pending
        assert r.can_be_approved_by('ca') is True
        assert r.can_be_approved_by('boss') is True    # admin may approve someone else's
        assert r.can_be_approved_by('acc') is False    # never self

    def test_can_be_approved_by_rejects_wrong_role_or_inactive(self, db_session):
        _user('acc', 'accountant'); _user('ca', 'chief_accountant')
        staff = _user('bob', 'staff')
        r = _req('acc')
        assert r.can_be_approved_by('bob') is False
        staff.is_active = False; db.session.commit()
        assert r.can_be_approved_by('bob') is False

    def test_can_be_approved_by_rejects_deactivated_valid_role_reviewer(self, db_session):
        # A valid-ROLE reviewer (accountant) who is DEACTIVATED must not approve. This
        # uniquely exercises the is_active guard -- the wrong-role test above short-circuits
        # on the role check before the inactive branch is ever reached.
        _user('acc', 'accountant'); _user('ca', 'chief_accountant')
        acc2 = _user('acc2', 'accountant')
        r = _req('acc')  # peer present -> pending
        assert r.can_be_approved_by('acc2') is True   # active accountant peer -> can approve
        acc2.is_active = False; db.session.commit()
        assert r.can_be_approved_by('acc2') is False   # deactivated -> blocked
