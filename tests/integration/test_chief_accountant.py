import pytest
from app import db
from app.users.forms import UserForm

pytestmark = [pytest.mark.integration]


def test_fixture_is_chief_accountant(chief_accountant_user):
    assert chief_accountant_user.role == 'chief_accountant'
    assert chief_accountant_user.has_full_access is True
    assert chief_accountant_user.is_admin is False


def test_userform_accepts_chief_accountant_without_branch(app):
    # Chief Accountant, like admin, needs no branch assignment.
    with app.test_request_context():
        form = UserForm(meta={'csrf': False})
        form.role.data = 'chief_accountant'
        form.branch_ids.data = []
        form.validate_branch_ids(form.branch_ids)  # must not raise
