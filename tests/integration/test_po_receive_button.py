"""A receivable Purchase Order has a Receive button that opens a pre-filled receipt.

Owner, 2026-09-23: "PR can be converted to PO, can we do the same with PO to RR?" --
and on 2026-09-25 chose: a Receive button on the PO that opens a new Receiving Report
with that PO's vendor and ALL its outstanding quantities pre-filled; the receiver edits
quantities down to what actually arrived, then saves.

A PO is received partially and repeatedly, so "pre-filled" means the OPEN quantity of
each line (ordered minus what other receipts already took), never the ordered quantity.
The pre-fill reuses the form's own EXISTING map -- the path a bounced save already uses --
so no new client code exists to go wrong. It is only ever a starting point: the save
re-measures every ceiling (assert_payload_within_open_qty), whatever the page offered.
"""
import json
import re
from decimal import Decimal

import pytest

from tests.integration.test_rr_form_render import (_login, _po, _draft_rr, _run_line_block,
                                                   _vendor_select, rr_enabled)  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _embedded(body, name):
    marker = f'const {name} = '
    value, _ = json.JSONDecoder().raw_decode(body, body.index(marker) + len(marker))
    return value


def _committed_rr(db_session, branch, vendor, po, number, qty):
    """An earlier receipt that COUNTS against the order. A draft does not: open quantity
    subtracts only COMMITTED_STATUSES (receiving_reports/models.py::po_line_open_qty)."""
    from app.receiving_reports.models import COMMITTED_STATUSES
    rr = _draft_rr(db_session, branch, vendor, po, number=number, qty=qty)
    rr.status = COMMITTED_STATUSES[0]
    db_session.commit()
    return rr


def _create(client, po_id):
    resp = client.get(f'/receiving-reports/create?po_id={po_id}')
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


class TestThePrefilledReceipt:

    def test_the_vendor_is_selected_and_every_open_line_is_prefilled(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled, tmp_path):
        po = _po(db_session, main_branch, vl_vendor, 'PO-RCV-001', qty=10)
        _login(client, admin_user, main_branch)

        body = _create(client, po.id)

        select = _vendor_select(body)
        option = re.search(r'<option[^>]*value="%d"[^>]*>' % vl_vendor.id, select)
        assert option and 'selected' in option.group(0), 'the PO vendor is not preselected'
        poi = po.line_items[0].id
        assert _embedded(body, 'EXISTING') == {str(poi): 10.0}
        # ...and the real line block actually puts it on the page.
        assert 'PO-RCV-001' in _run_line_block(tmp_path, body, 'load')['before']

    def test_a_partly_received_po_prefills_only_what_is_still_open(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        po = _po(db_session, main_branch, vl_vendor, 'PO-RCV-002', qty=10,
                 status='partially_received')
        _committed_rr(db_session, main_branch, vl_vendor, po, 'RR-RCV-EARLIER', Decimal('4'))
        _login(client, admin_user, main_branch)

        body = _create(client, po.id)

        assert _embedded(body, 'EXISTING') == {str(po.line_items[0].id): 6.0}

    def test_a_non_receivable_po_opens_a_blank_receipt_with_a_notice(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        po = _po(db_session, main_branch, vl_vendor, 'PO-RCV-003', status='draft')
        _login(client, admin_user, main_branch)

        body = _create(client, po.id)

        assert _embedded(body, 'EXISTING') == {}
        assert 'cannot be received' in body

    def test_a_po_of_another_branch_is_not_prefilled(
            self, client, db_session, admin_user, main_branch, branch_manila, vl_vendor, rr_enabled):
        """Branch comes from the session, never from the query string (the open-lines
        route's rule). A foreign PO id gives a blank receipt and reveals nothing about it."""
        po = _po(db_session, branch_manila, vl_vendor, 'PO-RCV-OTHER')
        _login(client, admin_user, main_branch)

        body = _create(client, po.id)

        assert _embedded(body, 'EXISTING') == {}
        assert 'PO-RCV-OTHER' not in body

    def test_a_fully_received_line_is_left_out(
            self, client, db_session, admin_user, main_branch, vl_vendor, rr_enabled):
        from app.purchase_orders.models import PurchaseOrderItem
        po = _po(db_session, main_branch, vl_vendor, 'PO-RCV-004', qty=5, status='partially_received')
        po.line_items.append(PurchaseOrderItem(line_number=2, description='Sand', quantity=Decimal('3'),
                                               unit_price=Decimal('1'), amount=Decimal('3')))
        po.calculate_totals(); db_session.commit()
        _committed_rr(db_session, main_branch, vl_vendor, po, 'RR-RCV-FULL', Decimal('5'))
        _login(client, admin_user, main_branch)

        body = _create(client, po.id)

        assert _embedded(body, 'EXISTING') == {str(po.line_items[1].id): 3.0}


class TestTheButton:

    def _detail(self, client, po):
        return client.get(f'/purchase-orders/{po.id}').get_data(as_text=True)

    def _button(self, body, po):
        return re.search(r'<a[^>]*href="/receiving-reports/create\?po_id=%d"[^>]*>\s*Receive\s*</a>' % po.id,
                         body)

    @pytest.mark.parametrize('status', ['submitted', 'approved', 'partially_received'])
    def test_a_receivable_po_shows_it(self, client, db_session, admin_user, main_branch, vl_vendor,
                                      rr_enabled, status):
        po = _po(db_session, main_branch, vl_vendor, f'PO-BTN-{status}', status=status)
        _login(client, admin_user, main_branch)
        assert self._button(self._detail(client, po), po)

    @pytest.mark.parametrize('status', ['draft', 'received', 'cancelled'])
    def test_a_po_that_cannot_be_received_does_not(self, client, db_session, admin_user, main_branch,
                                                   vl_vendor, rr_enabled, status):
        po = _po(db_session, main_branch, vl_vendor, f'PO-NOBTN-{status}', status=status)
        _login(client, admin_user, main_branch)
        body = self._detail(client, po)
        assert f'/purchase-orders/{po.id}' in body or po.po_number in body, 'anti-vacuity'
        assert not self._button(body, po)

    def test_a_viewer_does_not_see_it(self, client, db_session, viewer_user, main_branch, vl_vendor,
                                      rr_enabled):
        po = _po(db_session, main_branch, vl_vendor, 'PO-BTN-VIEWER', status='approved')
        viewer_user.set_branches([main_branch]); db_session.commit()   # else: branch picker
        _login(client, viewer_user, main_branch)
        body = self._detail(client, po)
        assert 'PO-BTN-VIEWER' in body, 'anti-vacuity: the viewer can open the PO'
        assert not self._button(body, po)

    def test_it_is_hidden_when_receiving_reports_is_off(self, client, db_session, admin_user,
                                                        main_branch, vl_vendor, rr_enabled):
        from app.settings import AppSettings
        from app.utils.cache_helpers import clear_module_config_cache
        po = _po(db_session, main_branch, vl_vendor, 'PO-BTN-OFF', status='approved')
        AppSettings.set_setting('module_enabled:receiving_reports', '0'); db_session.commit()
        clear_module_config_cache()
        _login(client, admin_user, main_branch)
        body = self._detail(client, po)
        assert 'PO-BTN-OFF' in body, 'anti-vacuity'
        assert not self._button(body, po)
