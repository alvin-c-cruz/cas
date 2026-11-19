"""Playwright e2e for app/static/js/rr_no_po_matches.js -- what the RR form's "no purchase order" warning offers
(RR-1 A, owner 17 Nov 2026; work order 2026-11-13-rr-received-without-po-link).

Before: only open PO lines for the SAME product were offered, so a receiver who picked a new product (RR 00780: 767
against PO 02012's 555) saw no warning at all. Now every open line of the vendor in the branch is offered, same
product first, each as a "Receive against" button; going on without a PO still needs a typed reason.

Driven in a real browser engine on a blank page that loads only the script under test.
"""
import functools
import http.server
import os
import socket
import threading

import pytest

pytestmark = [pytest.mark.e2e]

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

ROWS = [
    {'purchase_order_item_id': 11, 'po_number': '02012', 'product_id': 555, 'product_name': 'SPIN DRYER', 'open': 1},
    {'purchase_order_item_id': 12, 'po_number': '02015', 'product_id': 700, 'product_name': 'HOSE', 'open': 4},
    {'purchase_order_item_id': 13, 'po_number': '02016', 'product_id': None, 'product_name': 'INSTALLATION', 'open': 1},
    {'purchase_order_item_id': 14, 'po_number': '02017', 'product_id': 767, 'product_name': 'WHIRPOOL DRYER', 'open': 2},
    {'purchase_order_item_id': 15, 'po_number': '02018', 'product_id': 701, 'product_name': 'DONE', 'open': 0},
]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope='module')
def static_server():
    handler = functools.partial(_QuietHandler, directory=PROJECT_ROOT)
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        httpd.shutdown(); httpd.server_close(); thread.join(timeout=5)


@pytest.fixture
def js(page, static_server):
    page.goto(static_server + '/app/static/css/style.css')        # any same-origin page
    page.add_script_tag(url=static_server + '/app/static/js/rr_no_po_matches.js')
    return page


def test_same_product_first_then_the_others(js):
    m = js.evaluate('rows => rrNoPoMatches(rows, 767)', ROWS)
    assert [r['po_number'] for r in m['same']] == ['02017']
    assert [r['po_number'] for r in m['others']] == ['02012', '02015', '02016'], 'closed-out line (open 0) dropped'
    assert m['moreOthers'] == 0


def test_a_new_product_still_sees_the_vendors_open_lines(js):
    """RR 00780's case: the chosen product is on no open order line."""
    m = js.evaluate('rows => rrNoPoMatches(rows, 999)', ROWS)
    assert m['same'] == []
    assert [r['po_number'] for r in m['others']] == ['02012', '02015', '02016', '02017']
    text = js.evaluate('m => rrNoPoWarningText(m)', m)
    assert 'open purchase-order lines' in text and 'receive it against that order' in text


def test_nothing_open_means_no_warning(js):
    m = js.evaluate('rows => rrNoPoMatches(rows, 555)', [ROWS[4]])
    assert m['same'] == [] and m['others'] == []
    assert js.evaluate('m => rrNoPoWarningText(m)', m) == ''


def test_the_others_are_capped_with_a_pointer_to_pull(js):
    many = [dict(ROWS[1], purchase_order_item_id=100 + i, po_number=f'0{3000 + i}') for i in range(12)]
    m = js.evaluate('rows => rrNoPoMatches(rows, 999, 8)', many)
    assert len(m['others']) == 8 and m['moreOthers'] == 4
    assert '4 more' in js.evaluate('m => rrNoPoWarningText(m)', m)


def test_button_labels_name_the_order_and_for_others_the_item(js):
    same = js.evaluate('r => rrNoPoButtonLabel(r, true)', ROWS[3])
    other = js.evaluate('r => rrNoPoButtonLabel(r, false)', ROWS[0])
    assert same == 'Receive against 02017'
    assert other == 'Receive against 02012: SPIN DRYER (1 open)'
