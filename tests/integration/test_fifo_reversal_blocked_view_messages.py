"""One test per bare (no prior try/except) call site -- RR/DR/WO cancel, the
three that would otherwise 500 -- proving a FifoLayerConsumedError raised by
the reversal function reaches the user as a flashed message instead.
Monkeypatches the reversal function itself: Task 5's own unit tests already
prove WHEN/WHY it raises; this proves each VIEW's try/except actually
catches it. The other two call sites (purchase_memos/sales_memos _void_impl)
get a one-line `except ValueError` branch added above their existing
`except Exception` in Step 4 below -- a mechanical change already exercised
by each file's own large existing void-route test suite (confirmed via the
Step 6 regression sweep), so it doesn't need a bespoke fixture-heavy test
here."""
from datetime import date
from decimal import Decimal
import pytest
from app.stock_adjustments.service import FifoLayerConsumedError

D = Decimal


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    """These three cancel routes are gated by enforce_module_access (an
    optional module disabled at the instance level 404s for ALL roles,
    including admin) -- mirrors the autouse fixture in
    tests/integration/test_receiving_report_stock_posting.py. Not part of
    the brief's illustrative test snippet (it predates discovering the
    module gate, since the brief's own tests exercised
    reverse_rr_receipt/reverse_dr_delivery/reverse_consumption directly,
    bypassing routing); required for these 3 tests, which hit the routes
    over HTTP, to reach the view body instead of 404ing at the gate."""
    from app.settings import AppSettings
    for key in ('receiving_reports', 'delivery_receipts', 'work_orders'):
        AppSettings.set_setting(f'module_enabled:{key}', '1', updated_by='test')
    db_session.commit()
    yield


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_rr_cancel_surfaces_fifo_blocked_message(client, db_session, admin_user, branch_main, monkeypatch):
    from app.receiving_reports.models import ReceivingReport
    from app import db
    # purchase_order_id is a real NOT NULL FK but SQLite FK enforcement is
    # off app-wide in this app (see memory sqlite-fk-off-delete-guard) -- a
    # dummy non-referential id satisfies the NOT NULL constraint without a
    # full PurchaseOrder fixture chain, which this test has no other reason
    # to build.
    rr = ReceivingReport(rr_number='RR-2026-07-9001', branch_id=branch_main.id,
                         receipt_date=date(2026, 7, 22), purchase_order_id=1,
                         vendor_name='Test Vendor', status='approved')
    db.session.add(rr); db.session.commit()

    def _raise(*a, **k):
        raise FifoLayerConsumedError('Cannot reverse movement 1 -- 4.0000 of 10.0000 units already consumed by other_doc #2.')
    monkeypatch.setattr('app.receiving_reports.stock_posting.reverse_rr_receipt', _raise)

    _login(client, admin_user, branch_main)
    resp = client.post(f'/receiving-reports/{rr.id}/cancel',
                       data={'cancel_reason': 'testing FIFO block path'}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'already consumed' in resp.data


def test_dr_cancel_surfaces_fifo_blocked_message(client, db_session, admin_user, branch_main, monkeypatch):
    from app.delivery_receipts.models import DeliveryReceipt
    from app import db
    # sales_order_id/customer_id are real NOT NULL FKs but SQLite FK
    # enforcement is off app-wide in this app (see memory
    # sqlite-fk-off-delete-guard) -- a dummy non-referential id satisfies the
    # NOT NULL constraint without needing a full SalesOrder/Customer fixture
    # chain, which this test has no other reason to build.
    dr = DeliveryReceipt(dr_number='DR-2026-07-9001', branch_id=branch_main.id,
                         delivery_date=date(2026, 7, 22), sales_order_id=1, customer_id=1,
                         customer_name='Test Customer', status='approved')
    db.session.add(dr); db.session.commit()

    def _raise(*a, **k):
        raise FifoLayerConsumedError('Cannot reverse movement 2 -- already consumed by other_doc #3.')
    monkeypatch.setattr('app.delivery_receipts.stock_posting.reverse_dr_delivery', _raise)

    _login(client, admin_user, branch_main)
    resp = client.post(f'/delivery-receipts/{dr.id}/cancel',
                       data={'cancel_reason': 'testing FIFO block path'}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'already consumed' in resp.data


def test_wo_cancel_surfaces_fifo_blocked_message(client, db_session, admin_user, branch_main,
                                                  product_fifo, monkeypatch):
    from app.work_orders.models import WorkOrder
    from app.bill_of_materials.models import BillOfMaterial
    from app import db
    # Unlike the RR/DR fixtures above, a dummy non-referential bom_id doesn't
    # work here: the cancel route redirects to work_orders.view on BOTH the
    # success and the caught-exception path, and that template dereferences
    # wo.bom.product unconditionally -- a dangling FK renders wo.bom as None
    # (SQLite FK enforcement is off app-wide) and the GET after redirect 500s
    # on 'None' has no attribute 'product', masking the very flash message
    # this test exists to prove. So this fixture needs a REAL BillOfMaterial
    # (via the product_fifo fixture) rather than a dummy id.
    bom = BillOfMaterial(product_id=product_fifo.id, manufacturing_mode='discrete', is_active=True)
    db.session.add(bom); db.session.commit()
    wo = WorkOrder(wo_number='WO-2026-07-9001', branch_id=branch_main.id, bom_id=bom.id,
                   qty_to_produce=D('1'), status='released')
    db.session.add(wo); db.session.commit()

    def _raise(*a, **k):
        raise FifoLayerConsumedError('Cannot reverse movement 3 -- already consumed by other_doc #4.')
    monkeypatch.setattr('app.work_orders.service.reverse_consumption', _raise)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch_main.id
    resp = client.post(f'/work-orders/{wo.id}/cancel',
                       data={'cancel_reason': 'testing FIFO block path'}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'already consumed' in resp.data
