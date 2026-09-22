"""A Receiving Report is printable only once it has been submitted.

Owner decision 2026-09-21: a receiver was printing receipts still in DRAFT. A draft
is a scratchpad -- it can still be edited or deleted -- so a printed one is a piece
of paper that no longer matches the record, signed by whoever was handed it.

This OVERTURNS an earlier deliberate choice, recorded in print_rr's own docstring:
that an RR, unlike a PO, never reaches a supplier, so the commercial risk that
justifies refusing to print a draft order does not apply. That argument was about
the SUPPLIER's copy; the owner's objection is about the internal one, where a signed
draft is evidence of a count that the record can still contradict.

Enforced at the ROUTE, not only by hiding the button: a direct GET bypasses the
template entirely -- the same reasoning purchase_orders/views.py gives for its gate.
"""
from datetime import date

import pytest

from app.receiving_reports.models import ReceivingReport
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture(autouse=True)
def rr_enabled(db_session):
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
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


def _rr(db_session, branch, vendor, status, number):
    r = ReceivingReport(rr_number=number, receipt_date=date(2026, 8, 19),
                        branch_id=branch.id, vendor_id=vendor.id,
                        vendor_name=vendor.name, status=status)
    db_session.add(r); db_session.commit()
    return r


class TestPrintingIsGatedOnSubmit:

    def test_a_draft_is_refused(self, client, db_session, admin_user, main_branch,
                                vl_vendor):
        rr = _rr(db_session, main_branch, vl_vendor, 'draft', 'RR-GATE-DRAFT')
        _login(client, admin_user, main_branch)

        resp = client.get(f'/receiving-reports/{rr.id}/print', follow_redirects=True)

        assert b'Submit it first' in resp.data
        assert b'Prepared by' not in resp.data, \
            'the printout rendered anyway -- the redirect must replace it, not precede it'

    def test_a_submitted_receipt_prints(self, client, db_session, admin_user,
                                        main_branch, vl_vendor):
        """The whole point of the change: submitting is what makes it printable."""
        rr = _rr(db_session, main_branch, vl_vendor, 'submitted', 'RR-GATE-SUBM')
        _login(client, admin_user, main_branch)

        resp = client.get(f'/receiving-reports/{rr.id}/print')

        assert resp.status_code == 200
        assert b'Prepared by' in resp.data

    def test_an_approved_receipt_still_prints(self, client, db_session, admin_user,
                                              main_branch, vl_vendor):
        """CONTROL. The gate must catch DRAFT only -- everything downstream of
        submit was printable before this change and must stay printable."""
        rr = _rr(db_session, main_branch, vl_vendor, 'approved', 'RR-GATE-APPR')
        _login(client, admin_user, main_branch)

        assert client.get(f'/receiving-reports/{rr.id}/print').status_code == 200

    def test_a_billed_receipt_still_prints(self, client, db_session, admin_user,
                                           main_branch, vl_vendor):
        """CONTROL, and the one most likely to be wanted on paper after the fact."""
        rr = _rr(db_session, main_branch, vl_vendor, 'billed', 'RR-GATE-BILL')
        _login(client, admin_user, main_branch)

        assert client.get(f'/receiving-reports/{rr.id}/print').status_code == 200


class TestTheButtonMatchesTheRoute:
    """A button the route refuses is a bug report waiting to happen -- but the
    button is never the enforcement (see the module docstring)."""

    def test_the_detail_page_offers_no_print_button_for_a_draft(
            self, client, db_session, admin_user, main_branch, vl_vendor):
        rr = _rr(db_session, main_branch, vl_vendor, 'draft', 'RR-GATE-BTN-D')
        _login(client, admin_user, main_branch)

        body = client.get(f'/receiving-reports/{rr.id}').data.decode()

        # Scoped to the APPLIED href, never the bare word 'print': the page's inline
        # script and stylesheet both contain it, so a bare-substring assertion here
        # could never fail.
        assert f'/receiving-reports/{rr.id}/print' not in body

    def test_the_detail_page_offers_print_once_submitted(
            self, client, db_session, admin_user, main_branch, vl_vendor):
        rr = _rr(db_session, main_branch, vl_vendor, 'submitted', 'RR-GATE-BTN-S')
        _login(client, admin_user, main_branch)

        body = client.get(f'/receiving-reports/{rr.id}').data.decode()

        assert f'/receiving-reports/{rr.id}/print' in body
