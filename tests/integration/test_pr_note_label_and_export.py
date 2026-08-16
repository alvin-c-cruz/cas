"""Purchase Requisition: the header free-text field is called Note, and the
export's headers line up with its columns.

Two things, both about the same field.

1. RENAME. The field labelled "Reason / Justification" is now "Note" -- owner
   directive 2026-08-14. The stored column stays `reason`; only what the user
   reads changes, so there is no migration and no risk to existing data. The
   rename has to reach create, edit, detail, LIST and PRINT together: a document
   whose surfaces disagree about what a field is called is the defect
   `feedback-si-surface-consistency` exists to prevent.

   Two OTHER labels containing "Reason" belong to different fields and must NOT
   move -- `amend_reason` ("Reason for amendment") and the shared
   reject/cancel modal's own reason box. Controls below pin both.

2. THE EXPORT PAIRING. _EXPORT_COLUMNS and _EXPORT_HEADERS are two parallel
   lists handed to export_to_excel as separate arguments, so nothing forces them
   to stay the same length. Adding date_needed and date_needed_asap to the
   columns (commits 9afb0e47 and 6b884347) without touching the headers left 7
   columns under 5 headers -- every label after "Request Date" describing the
   wrong column. A length assertion is cheap and would have caught it the moment
   it happened.
"""
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest
from app.purchase_requests import views as pr_views

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_requests', 'units_of_measure'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def pr(db_session, admin_user, main_branch):
    p = PurchaseRequest(pr_number='NOTE-1', request_date=date(2026, 8, 14),
                        reason='Attention: Anissa Tang', branch_id=main_branch.id,
                        status='draft', created_by_id=admin_user.id)
    db_session.add(p)
    db_session.commit()
    return p


class TestTheExportHeadersMatchItsColumns:
    """The bug this file was written for."""

    def test_the_two_lists_are_the_same_length(self):
        assert len(pr_views._EXPORT_COLUMNS) == len(pr_views._EXPORT_HEADERS), (
            f'{len(pr_views._EXPORT_COLUMNS)} columns under '
            f'{len(pr_views._EXPORT_HEADERS)} headers -- every label after the '
            'mismatch describes the wrong column')

    def test_the_new_date_columns_have_labels(self):
        """Named explicitly so a future column addition that forgets its header
        fails on something readable, not just a count."""
        pairs = dict(zip(pr_views._EXPORT_COLUMNS, pr_views._EXPORT_HEADERS))
        assert pairs.get('date_needed') == 'Date Needed'
        assert pairs.get('date_needed_asap') == 'ASAP'

    def test_the_note_column_is_labelled_note(self):
        pairs = dict(zip(pr_views._EXPORT_COLUMNS, pr_views._EXPORT_HEADERS))
        assert pairs.get('reason') == 'Note'

    def test_the_excel_export_still_builds(self, client, admin_user, main_branch, pr):
        """Executes the real exporter rather than only inspecting the lists --
        a mismatch that raises would otherwise surface first for a user."""
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-requests/export/excel')
        assert resp.status_code == 200
        assert len(resp.data) > 0

    def test_the_csv_export_still_builds(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-requests/export/csv')
        assert resp.status_code == 200
        assert b'Note' in resp.data, 'the CSV header row does not carry the new label'


class TestEverySurfaceSaysNote:

    def test_the_create_form(self, client, admin_user, main_branch):
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-requests/create').data.decode()
        assert 'Note' in html
        assert 'Reason / Justification' not in html

    def test_the_edit_form(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}/edit').data.decode()
        assert 'Note' in html
        assert 'Reason / Justification' not in html

    def test_the_detail_page(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'Note:' in html
        assert 'Attention: Anissa Tang' in html

    def test_the_list_page(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-requests').data.decode()
        assert '<th>Note</th>' in html

    def test_the_printout(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}/print').data.decode()
        assert '<th>Note</th>' in html
        assert 'Attention: Anissa Tang' in html


class TestTheOtherReasonFieldsAreUntouched:
    """Controls. Three different fields spell 'reason'; only the header one was
    renamed. Renaming the wrong one changes what an approver is asked for."""

    def test_the_amend_reason_label_is_unchanged(self):
        from app.purchase_requests.forms import PurchaseRequestAmendForm
        # A class-level WTForms field is an UnboundField; a label passed
        # positionally (as this one is) lands in .args, not .kwargs. Reading only
        # kwargs made this control fail against correct code.
        fld = PurchaseRequestAmendForm.amend_reason
        label = fld.args[0] if fld.args else fld.kwargs.get('label')
        assert label == 'Reason for amendment'

    def test_the_cancel_modal_still_asks_for_a_reason(self, client, admin_user,
                                                      main_branch, pr):
        """The shared reject/cancel modal has its own reason box, unrelated to
        the header field."""
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'Reason (at least 10 characters)' in html

    def test_the_stored_column_is_still_reason(self, pr):
        """The rename is presentation only -- no migration, and `reason` remains
        the attribute every view, snapshot and export column refers to."""
        assert pr.reason == 'Attention: Anissa Tang'
        assert 'reason' in PurchaseRequest.SNAPSHOT_HEADER_FIELDS
