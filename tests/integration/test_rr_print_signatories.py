"""Editable signatories on the Receiving Report printout, and the ruled grid.

Company-level (AppSettings rows, no model change), mirroring the Purchase
Requisition's mechanism -- but with its OWN keys. The code is shared; the VALUES
are not. A company routinely names different people on a receipt than on a
requisition, so `rr_sig*` and `pr_sig*` must never read each other.
"""
import re
from datetime import date

import pytest

from app.receiving_reports.models import ReceivingReport
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture(autouse=True)
def rr_enabled(db_session):
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def rr(db_session, admin_user, main_branch, vl_vendor):
    r = ReceivingReport(rr_number='RR-SIG-1', receipt_date=date(2026, 8, 19),
                        branch_id=main_branch.id, vendor_id=vl_vendor.id,
                        vendor_name='Johnson Hardware', status='draft',
                        remarks='CI #67050', created_by_id=admin_user.id)
    db_session.add(r)
    db_session.commit()
    return r


def _print(client, rr):
    return client.get(f'/receiving-reports/{rr.id}/print')


class TestSignatoryDefaults:

    def test_default_roles_match_the_paper_form(self, client, admin_user, main_branch, rr):
        _login(client, admin_user, main_branch)
        data = _print(client, rr).data
        assert b'Prepared by' in data
        assert b'Checked by' in data
        assert b'Received by' in data

    def test_an_unset_name_prints_a_blank_line_not_a_placeholder(
            self, client, admin_user, main_branch, rr):
        """A blank name is MEANINGFUL -- it prints an empty ruled line to sign by
        hand. Substituting the creator's name is the bug this design avoids."""
        _login(client, admin_user, main_branch)
        data = _print(client, rr).data
        sig = data.split(b'sig-row')[-1]
        assert admin_user.full_name.encode() not in sig


class TestSignatoriesAreIndependentOfThePurchaseRequisition:
    """The owner's explicit requirement: shared code, separate values."""

    def test_rr_keys_drive_the_rr_printout(self, client, db_session, admin_user,
                                           main_branch, rr):
        AppSettings.set_setting('rr_sig2_name', 'Fred Santos')
        AppSettings.set_setting('rr_sig2_role', 'Checked by')
        db_session.commit()
        _login(client, admin_user, main_branch)
        assert b'Fred Santos' in _print(client, rr).data

    def test_pr_signatories_do_NOT_leak_onto_the_receiving_report(
            self, client, db_session, admin_user, main_branch, rr):
        """Mutation target: a delegate that read the 'pr' prefix would print the
        requisition's people on every receipt."""
        AppSettings.set_setting('pr_sig1_name', 'Requisition Person')
        db_session.commit()
        _login(client, admin_user, main_branch)
        assert b'Requisition Person' not in _print(client, rr).data

    def test_saving_rr_signatories_leaves_pr_untouched(self, client, db_session,
                                                       admin_user, main_branch, rr):
        AppSettings.set_setting('pr_sig1_name', 'Requisition Person')
        db_session.commit()
        _login(client, admin_user, main_branch)
        client.post('/settings/rr-print-signatories', data={
            'rr_id': rr.id, 'rr_sig1_name': 'Receipt Person', 'rr_sig1_role': 'Prepared by',
        }, follow_redirects=True)
        assert AppSettings.get_setting('rr_sig1_name') == 'Receipt Person'
        assert AppSettings.get_setting('pr_sig1_name') == 'Requisition Person'


class TestSaveRoute:

    def test_saving_changes_what_prints_and_is_audited(self, client, db_session,
                                                       admin_user, main_branch, rr):
        from app.audit.models import AuditLog
        _login(client, admin_user, main_branch)
        resp = client.post('/settings/rr-print-signatories', data={
            'rr_id': rr.id,
            'rr_sig1_name': 'Angilyn Malapascua', 'rr_sig1_role': 'Prepared by',
            'rr_sig2_name': 'Fred Santos', 'rr_sig2_role': 'Checked by',
            'rr_sig3_name': 'Juan Dela Cruz', 'rr_sig3_role': 'Received by',
        }, follow_redirects=True)
        assert resp.status_code == 200
        data = _print(client, rr).data
        assert b'Angilyn Malapascua' in data
        assert b'Juan Dela Cruz' in data
        assert AuditLog.query.filter_by(
            record_identifier='rr_print_signatories').first() is not None

    def test_a_blank_role_falls_back_to_the_default_label(self, client, admin_user,
                                                          main_branch, rr):
        _login(client, admin_user, main_branch)
        client.post('/settings/rr-print-signatories', data={
            'rr_id': rr.id, 'rr_sig3_name': 'Juan', 'rr_sig3_role': '',
        }, follow_redirects=True)
        assert AppSettings.get_setting('rr_sig3_role') == 'Received by'

    def test_staff_cannot_change_the_signatories(self, client, db_session, staff_user,
                                                 main_branch, rr):
        """CONTROL on the authz gate -- accountant or full access only."""
        AppSettings.set_setting('rr_sig1_name', 'Original')
        db_session.commit()
        _login(client, staff_user, main_branch)
        client.post('/settings/rr-print-signatories', data={
            'rr_id': rr.id, 'rr_sig1_name': 'Injected',
        }, follow_redirects=True)
        assert AppSettings.get_setting('rr_sig1_name') == 'Original'


class TestRuledGrid:

    def test_the_grid_is_padded_to_a_fixed_number_of_rows(self, client, admin_user,
                                                          main_branch, rr):
        """The legacy sheet's look: ruled rows fill the page so the signature
        block lands in the same place on every receipt."""
        from app.receiving_reports.views import PRINT_MIN_ROWS
        _login(client, admin_user, main_branch)
        body = _print(client, rr).data.decode()
        fillers = len(re.findall(r'<tr class="filler">', body))
        assert fillers == PRINT_MIN_ROWS      # this RR has no lines of its own

    def test_the_document_name_is_in_the_MARKUP_not_only_the_css(
            self, client, admin_user, main_branch, rr):
        """Regression: the title was first emitted as 'Receiving Report' with a
        CSS text-transform, which renders uppercase but leaves the DOM -- and
        every assertion and reader looking for the document's name -- wrong."""
        _login(client, admin_user, main_branch)
        assert b'RECEIVING REPORT' in _print(client, rr).data

    def test_the_supporting_documents_reference_prints(self, client, admin_user,
                                                       main_branch, rr):
        _login(client, admin_user, main_branch)
        data = _print(client, rr).data
        assert b'Supporting Documents' in data
        assert b'CI #67050' in data
