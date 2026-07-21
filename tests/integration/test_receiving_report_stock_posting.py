# tests/integration/test_receiving_report_stock_posting.py
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.receiving_reports.stock_posting import post_rr_receipt, reverse_rr_receipt
from app.stock_adjustments.models import StockMovement, StockBalance
from app.posting.control_accounts import ControlAccountError
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def rr_enabled(db_session):
    """HTTP-level tests hit routes gated by enforce_module_access -- mirrors
    tests/integration/test_receiving_reports_lifecycle.py's own autouse fixture
    (this file previously only called post_rr_receipt/reverse_rr_receipt directly,
    which bypasses routing entirely, so this gate was never needed until now)."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _assign(code_setting, code, account_factory):
    account_factory(code)
    AppSettings.set_setting(code_setting, code, updated_by='test')


def _approved_po(db_session, branch, vendor, product, unit_price='10.00', vat_rate='12.00', qty=100):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number='PO-2A2-0001', order_date=date(2026, 7, 21),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description=product.name,
                                           product_id=product.id, quantity=Decimal(str(qty)),
                                           unit_price=Decimal(unit_price), vat_rate=Decimal(vat_rate),
                                           amount=Decimal(unit_price) * qty))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _draft_rr(db_session, branch, po, received, number='RR-2A2-0001'):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 21),
                         purchase_order_id=po.id, vendor_id=po.vendor_id,
                         vendor_name=po.vendor_name, status='draft')
    rr.line_items.append(ReceivingReportItem(line_number=1,
                                             purchase_order_item_id=po.line_items[0].id,
                                             product_id=po.line_items[0].product_id,
                                             received_quantity=Decimal(str(received))))
    db_session.add(rr); db_session.commit()
    return rr


def test_tracked_line_posts_movement_and_net_of_vat_je(
        db_session, branch_main, admin_user, product_tracked, vl_vendor, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    po = _approved_po(db_session, branch_main, vl_vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _draft_rr(db_session, branch_main, po, received=10)

    post_rr_receipt(rr, admin_user)
    db.session.commit()

    assert rr.journal_entry_id is not None
    assert rr.journal_entry.is_balanced
    mv = StockMovement.query.filter_by(source_document_type='receiving_report', source_document_id=rr.id).one()
    # 11.20 gross / 1.12 = 10.00 net per unit -> 10 units = 100.00 net
    assert mv.unit_cost == Decimal('10.00')
    assert mv.quantity == Decimal('10.0000')
    assert rr.line_items[0].stock_movement_id == mv.id
    dr = next(l for l in rr.journal_entry.lines if l.account.code == '1401')
    cr = next(l for l in rr.journal_entry.lines if l.account.code == '2015')
    assert dr.debit_amount == Decimal('100.00') and cr.credit_amount == Decimal('100.00')
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('10.0000')


def test_untracked_line_posts_nothing(db_session, branch_main, admin_user, vl_vendor, make_account):
    from app.products.models import Product
    untracked = Product(code='UNTRK-1', name='Untracked Item', track_inventory=False, is_active=True)
    db.session.add(untracked); db.session.commit()
    po = _approved_po(db_session, branch_main, vl_vendor, untracked, qty=5)
    rr = _draft_rr(db_session, branch_main, po, received=5)

    post_rr_receipt(rr, admin_user)  # no accounts assigned at all -- must not raise
    db.session.commit()

    assert rr.journal_entry_id is None
    assert rr.line_items[0].stock_movement_id is None
    assert StockMovement.query.count() == 0


def test_fails_closed_before_any_write_when_grni_unassigned(
        db_session, branch_main, admin_user, product_tracked, vl_vendor, make_account):
    _assign('inventory_account_code', '1401', make_account)  # grni left unassigned
    po = _approved_po(db_session, branch_main, vl_vendor, product_tracked, qty=10)
    rr = _draft_rr(db_session, branch_main, po, received=10)

    with pytest.raises(ControlAccountError):
        post_rr_receipt(rr, admin_user)
    assert rr.journal_entry_id is None
    assert StockMovement.query.count() == 0


def test_reverse_rr_receipt_reverses_movement_and_posts_reversing_je(
        db_session, branch_main, admin_user, product_tracked, vl_vendor, make_account):
    from app.journal_entries.models import JournalEntry
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    po = _approved_po(db_session, branch_main, vl_vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _draft_rr(db_session, branch_main, po, received=10)
    post_rr_receipt(rr, admin_user); db.session.commit()
    original_je_id = rr.journal_entry_id

    reverse_rr_receipt(rr, admin_user)
    db.session.commit()

    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('0.0000')
    reversing_jes = JournalEntry.query.filter_by(reference=rr.rr_number).order_by(JournalEntry.id).all()
    assert len(reversing_jes) == 2
    assert reversing_jes[1].id != original_je_id
    reversal_mv = (StockMovement.query
                  .filter_by(source_document_type='receiving_report', source_document_id=rr.id)
                  .filter(StockMovement.quantity < 0).one())
    assert reversal_mv.journal_entry_id == reversing_jes[1].id


def test_reverse_rr_receipt_noop_when_never_posted(db_session, branch_main, admin_user, vl_vendor, make_account):
    from app.products.models import Product
    untracked = Product(code='UNTRK-2', name='Untracked Item 2', track_inventory=False, is_active=True)
    db.session.add(untracked); db.session.commit()
    po = _approved_po(db_session, branch_main, vl_vendor, untracked, qty=5)
    rr = _draft_rr(db_session, branch_main, po, received=5)
    post_rr_receipt(rr, admin_user); db.session.commit()

    reverse_rr_receipt(rr, admin_user)  # no JE was ever posted -- must be a clean no-op
    db.session.commit()
    from app.journal_entries.models import JournalEntry
    assert JournalEntry.query.filter_by(reference=rr.rr_number).count() == 0


def _login(client, user, branch):
    # accountant_user (tests/conftest.py) is only assigned to main_branch, not
    # branch_main (this file's own branch fixture) -- grant it explicitly so the
    # app's real before_request branch-access gate (app/__init__.py) doesn't
    # silently swap session['selected_branch_id'] back to main_branch and 404
    # _rr_or_404's branch-match check.
    if branch not in user.branches:
        user.set_branches(list(user.branches) + [branch])
        db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_approve_route_posts_grni_je(
        client, db_session, accountant_user, branch_main, product_tracked, vl_vendor, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    po = _approved_po(db_session, branch_main, vl_vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _draft_rr(db_session, branch_main, po, received=10, number='RR-2A2-APPROVE-1')
    _login(client, accountant_user, branch_main)

    resp = client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(rr)
    assert rr.status == 'approved'
    assert rr.journal_entry_id is not None


def test_approve_route_fails_closed_flashes_error_leaves_draft(
        client, db_session, accountant_user, branch_main, product_tracked, vl_vendor, make_account):
    # No control accounts assigned at all.
    po = _approved_po(db_session, branch_main, vl_vendor, product_tracked, qty=10)
    rr = _draft_rr(db_session, branch_main, po, received=10, number='RR-2A2-APPROVE-2')
    _login(client, accountant_user, branch_main)

    resp = client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(rr)
    assert rr.status == 'draft'   # still draft -- approval did NOT silently half-succeed


def test_cancel_route_reverses_grni_je(
        client, db_session, accountant_user, branch_main, product_tracked, vl_vendor, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    po = _approved_po(db_session, branch_main, vl_vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _draft_rr(db_session, branch_main, po, received=10, number='RR-2A2-CANCEL-1')
    _login(client, accountant_user, branch_main)
    client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)
    db.session.refresh(rr)
    assert rr.status == 'approved' and rr.journal_entry_id is not None

    resp = client.post(f'/receiving-reports/{rr.id}/cancel',
                       data={'cancel_reason': 'Damaged goods, returning to vendor'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(rr)
    assert rr.status == 'cancelled'
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == Decimal('0.0000')
