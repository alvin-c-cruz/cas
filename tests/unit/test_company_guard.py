"""Startup guard that stops a dev server from booting against the wrong company.

Two companies (philgen, ric) share this codebase locally, each on its own SQLite
file. The failure this guards against is a fix being tested for one company while
the server was silently restarted against the other -- the only visible tell was
the company name in the sidebar. The guard compares the launcher's declared
company against the `company_name` setting stored INSIDE the database, so the
data itself vouches for which company it belongs to.
"""
import pytest

from app.settings import AppSettings
from app.utils.company_guard import company_mismatch, COMPANY_MARKERS

pytestmark = [pytest.mark.unit]


def test_markers_cover_both_local_companies():
    assert 'philgen' in COMPANY_MARKERS
    assert 'ric' in COMPANY_MARKERS


def test_matching_company_returns_none(app, db_session):
    AppSettings.set_setting('company_name', 'Philgen Pacific Food Products Corporation')
    assert company_mismatch('philgen') is None


def test_marker_match_is_case_insensitive(app, db_session):
    AppSettings.set_setting('company_name', 'ROWELL INDUSTRIAL CORPORATION')
    assert company_mismatch('ric') is None


def test_wrong_company_names_both_sides(app, db_session):
    AppSettings.set_setting('company_name', 'ROWELL INDUSTRIAL CORPORATION')
    msg = company_mismatch('philgen')
    assert msg is not None
    assert 'philgen' in msg
    assert 'ROWELL INDUSTRIAL CORPORATION' in msg


def test_missing_company_name_is_a_mismatch(app, db_session):
    # A fresh/unseeded DB has no company_name row; refusing is the safe default.
    msg = company_mismatch('philgen')
    assert msg is not None
    assert '(not set)' in msg


def test_unknown_expected_company_is_rejected(app, db_session):
    AppSettings.set_setting('company_name', 'Philgen Pacific Food Products Corporation')
    msg = company_mismatch('acme')
    assert msg is not None
    assert 'acme' in msg
    assert 'philgen' in msg and 'ric' in msg  # tells the caller what IS valid
