"""Unit tests for Feature B — ApprovedEmailForm position + branch_ids."""
import pytest
from werkzeug.datastructures import MultiDict
from app.users.forms import ApprovedEmailForm

pytestmark = [pytest.mark.unit]


def _form(app, data, branch_choices=((1, 'Main'),)):
    with app.test_request_context():
        form = ApprovedEmailForm(formdata=MultiDict(data), meta={'csrf': False})
        form.branch_ids.choices = list(branch_choices)
        valid = form.validate()
        return form, valid


def test_position_required(app, db_session):
    form, valid = _form(app, {'email': 'x@example.ph', 'position': '', 'branch_ids': '1'})
    assert not valid
    assert 'position' in form.errors


def test_position_rejects_admin(app, db_session):
    """Admin is never a self-registration position — WTForms rejects an out-of-choice value."""
    form, valid = _form(app, {'email': 'x@example.ph', 'position': 'admin', 'branch_ids': '1'})
    assert not valid
    assert 'position' in form.errors


def test_position_accepts_accountant_staff_viewer(app, db_session):
    for pos in ('accountant', 'staff', 'viewer'):
        form, valid = _form(app, {'email': f'{pos}@example.ph', 'position': pos, 'branch_ids': '1'})
        assert valid, (pos, form.errors)
        assert form.position.data == pos


def test_branch_ids_coerced_to_int(app, db_session):
    form, valid = _form(app, {'email': 'x@example.ph', 'position': 'staff',
                              'branch_ids': '1'}, branch_choices=[(1, 'Main')])
    assert valid, form.errors
    assert form.branch_ids.data == [1]
