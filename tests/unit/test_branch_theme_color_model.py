"""Unit tests for Branch.theme_color (R-11 #231)."""
import pytest
from app.branches.models import Branch

pytestmark = [pytest.mark.branches, pytest.mark.unit]


def test_theme_color_defaults_to_none(db_session):
    branch = Branch(code='THM1', name='Theme Branch One')
    db_session.add(branch)
    db_session.commit()
    assert branch.theme_color is None


def test_theme_color_persists_hex_value(db_session):
    branch = Branch(code='THM2', name='Theme Branch Two', theme_color='#3b82f6')
    db_session.add(branch)
    db_session.commit()

    fetched = db_session.get(Branch, branch.id)
    assert fetched.theme_color == '#3b82f6'


def test_to_dict_includes_theme_color(db_session):
    branch = Branch(code='THM3', name='Theme Branch Three', theme_color='#22c55e')
    db_session.add(branch)
    db_session.commit()

    data = branch.to_dict()
    assert data['theme_color'] == '#22c55e'


def test_to_dict_theme_color_is_none_when_unset(db_session):
    branch = Branch(code='THM4', name='Theme Branch Four')
    db_session.add(branch)
    db_session.commit()

    assert branch.to_dict()['theme_color'] is None
