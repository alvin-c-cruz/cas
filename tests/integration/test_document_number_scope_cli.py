"""Task 8 -- the `set-document-number-scope` CLI.

The scope is deliberately NOT a Company Settings field: flipping it mid-year is
the riskiest action in the numbering system, so it should not be a dropdown any
admin can nudge. These tests pin the wiring, the validation, and the interleave
warning that makes a flip safe to perform.
"""
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest  # noqa: F401
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _invoke(app, *args):
    return app.test_cli_runner().invoke(
        app.cli.commands['set-document-number-scope'], list(args))


def test_command_is_registered(app):
    assert 'set-document-number-scope' in app.cli.commands


def test_sets_the_key(app, db_session):
    result = _invoke(app, 'branch')
    assert result.exit_code == 0, result.output
    assert AppSettings.get_setting('document_number_scope') == 'branch'
    assert 'company (unset) -> branch' in result.output


def test_rejects_an_unknown_value(app, db_session):
    AppSettings.set_setting('document_number_scope', 'company')
    result = _invoke(app, 'per-branch-oops')
    assert result.exit_code != 0
    assert 'Unknown scope' in result.output
    # the stored value must be untouched by a rejected call
    assert AppSettings.get_setting('document_number_scope') == 'company'


def test_warns_when_switching_to_branch_with_existing_documents(app, db_session):
    db_session.add(PurchaseRequest(pr_number='00598', request_date=date(2026, 8, 19),
                                   status='draft'))
    db_session.commit()
    result = _invoke(app, 'branch')
    assert result.exit_code == 0, result.output
    assert 'already holds numbered documents' in result.output
    assert 'interleaved' in result.output


def test_no_warning_on_an_empty_database(app, db_session):
    """CONTROL -- a fresh client has nothing to interleave."""
    result = _invoke(app, 'branch')
    assert result.exit_code == 0, result.output
    assert 'already holds numbered documents' not in result.output


def test_no_warning_when_switching_back_to_company(app, db_session):
    """CONTROL -- the reverse flip is inherently safe: a global max+1 is greater
    than every branch max, so it cannot collide."""
    db_session.add(PurchaseRequest(pr_number='00598', request_date=date(2026, 8, 19),
                                   status='draft'))
    db_session.commit()
    result = _invoke(app, 'company')
    assert result.exit_code == 0, result.output
    assert 'already holds numbered documents' not in result.output
