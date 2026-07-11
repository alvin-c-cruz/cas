"""Phase 3 end-to-end: billing POs/RRs through the AP create form + unbill on cancel/void.
Reuses the AP create-payload helpers from test_accounts_payable_attachments."""
import json
from datetime import date
from decimal import Decimal
import pytest

from tests.integration.test_accounts_payable_attachments import (
    login, make_vendor, _seed_je_accounts, _create_payload)

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _select_branch(client, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _approved_po(db_session, branch, vendor, number='PO-2026-07-0600', qty=100):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Subcontract',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _approved_rr(db_session, branch, po, number='RR-2026-07-0600', received=60):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 11),
                         purchase_order_id=po.id, vendor_id=po.vendor_id,
                         vendor_name=po.vendor_name, status='approved')
    rr.line_items.append(ReceivingReportItem(line_number=1,
                                             purchase_order_item_id=po.line_items[0].id,
                                             received_quantity=Decimal(str(received))))
    db_session.add(rr); db_session.commit()
    return rr


def _post_ap(client, vendor, account_id, ap_number, **extra):
    data = _create_payload(vendor, account_id, files=None)
    data['ap_number'] = ap_number
    data.update(extra)
    return client.post('/accounts-payable/create', data=data, follow_redirects=True)


def test_ap_bills_services_po_direct(client, db_session, accountant_user, main_branch):
    from app.purchase_orders.models import PurchaseOrder
    from app.journal_entries.models import JournalEntry
    login(client, 'accountant', 'accountant123'); _select_branch(client, main_branch)
    vendor = make_vendor(db_session, code='PBV1'); exp = _seed_je_accounts(db_session)
    po = _approved_po(db_session, main_branch, vendor)          # no RR -> billable direct
    je_before = JournalEntry.query.count()
    resp = _post_ap(client, vendor, exp.id, 'AP-BILL-1', source_po_ids=json.dumps([po.id]))
    assert resp.status_code == 200
    po = db_session.get(PurchaseOrder, po.id)
    assert po.status == 'closed' and po.accounts_payable_id is not None
    assert JournalEntry.query.count() == je_before + 1          # the Bill still posts its JE


def test_ap_bills_goods_rr(client, db_session, accountant_user, main_branch):
    from app.receiving_reports.models import ReceivingReport
    login(client, 'accountant', 'accountant123'); _select_branch(client, main_branch)
    vendor = make_vendor(db_session, code='PBV2'); exp = _seed_je_accounts(db_session)
    po = _approved_po(db_session, main_branch, vendor)
    rr = _approved_rr(db_session, main_branch, po)
    resp = _post_ap(client, vendor, exp.id, 'AP-BILL-2', source_rr_ids=json.dumps([rr.id]))
    assert resp.status_code == 200
    rr = db_session.get(ReceivingReport, rr.id)
    assert rr.status == 'billed' and rr.accounts_payable_id is not None


def test_ap_void_unbills_source(client, db_session, accountant_user, main_branch):
    from app.purchase_orders.models import PurchaseOrder
    from app.accounts_payable.models import AccountsPayable
    login(client, 'accountant', 'accountant123'); _select_branch(client, main_branch)
    vendor = make_vendor(db_session, code='PBV3'); exp = _seed_je_accounts(db_session)
    po = _approved_po(db_session, main_branch, vendor)
    _post_ap(client, vendor, exp.id, 'AP-BILL-3', source_po_ids=json.dumps([po.id]))
    ap = AccountsPayable.query.filter_by(ap_number='AP-BILL-3').first()
    assert db_session.get(PurchaseOrder, po.id).status == 'closed'
    client.post(f'/accounts-payable/{ap.id}/void',
                data={'void_reason': 'wrong bill entered', 'reversal_date': date.today().isoformat()},
                follow_redirects=True)
    po = db_session.get(PurchaseOrder, po.id)
    assert po.status == 'approved' and po.accounts_payable_id is None     # released


def test_stale_source_rolls_back_whole_bill(client, db_session, accountant_user, main_branch):
    from app.purchase_orders.models import PurchaseOrder
    from app.accounts_payable.models import AccountsPayable
    login(client, 'accountant', 'accountant123'); _select_branch(client, main_branch)
    vendor = make_vendor(db_session, code='PBV4'); exp = _seed_je_accounts(db_session)
    po = _approved_po(db_session, main_branch, vendor)
    po.status = 'closed'; db_session.commit()                  # already billed elsewhere -> stale
    resp = _post_ap(client, vendor, exp.id, 'AP-BILL-4', source_po_ids=json.dumps([po.id]))
    assert resp.status_code == 200
    assert AccountsPayable.query.filter_by(ap_number='AP-BILL-4').first() is None  # rolled back


def test_modules_off_ap_create_unaffected(client, db_session, accountant_user, main_branch):
    """Zhiyuan parity: with the PO/RR modules OFF, a normal AP create posts its JE and the
    billing hook is inert (no source ids in the form)."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    from app.accounts_payable.models import AccountsPayable
    from app.journal_entries.models import JournalEntry
    AppSettings.set_setting('module_enabled:purchase_orders', '0')
    AppSettings.set_setting('module_enabled:receiving_reports', '0')
    db_session.commit(); clear_module_config_cache()
    login(client, 'accountant', 'accountant123'); _select_branch(client, main_branch)
    vendor = make_vendor(db_session, code='PBV5'); exp = _seed_je_accounts(db_session)
    je_before = JournalEntry.query.count()
    resp = _post_ap(client, vendor, exp.id, 'AP-OFF-1')        # no source ids at all
    assert resp.status_code == 200
    ap = AccountsPayable.query.filter_by(ap_number='AP-OFF-1').first()
    assert ap is not None and ap.journal_entry_id is not None
    assert JournalEntry.query.count() == je_before + 1
