"""Regression tests for R-02 Phase 6: the AP create form must (a) submit the source PO/RR
item ids so the server can derive the variance snapshot, and (b) show a live client-side
notice when a picker-sourced line's price/qty is edited away from its matched value."""
import pytest

pytestmark = [pytest.mark.integration]


def test_create_form_submits_source_item_ids(client, accountant_user, main_branch):
    with client:
        client.post('/login', data={'username': accountant_user.username,
                                    'password': 'accountant123'}, follow_redirects=True)
        resp = client.get('/accounts-payable/create')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'source_po_item_id: item.source_po_item_id' in body
        assert 'source_rr_item_id: item.source_rr_item_id' in body


def test_create_form_has_variance_check_wired_to_qty_and_price_edits(client, accountant_user, main_branch):
    with client:
        client.post('/login', data={'username': accountant_user.username,
                                    'password': 'accountant123'}, follow_redirects=True)
        resp = client.get('/accounts-payable/create')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        assert 'function checkVariance(id)' in body
        update_start = body.index('function updateLineItem(id, field, value)')
        update_end = body.index('\n}\n', update_start)
        update_body = body[update_start:update_end]
        assert 'checkVariance(id)' in update_body, (
            "updateLineItem must call checkVariance(id) so qty/price edits re-check variance")
