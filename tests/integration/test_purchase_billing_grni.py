"""AP billing against a GRNI-accrued Receiving Report line (R-03 slice 2a-ii)."""
import json
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.settings import AppSettings
from app.receiving_reports.stock_posting import post_rr_receipt

from tests.integration.test_accounts_payable_attachments import login, make_vendor, _seed_je_accounts

pytestmark = [pytest.mark.integration]


def _assign(code_setting, code, account_factory):
    account_factory(code)
    AppSettings.set_setting(code_setting, code, updated_by='test')


def _select_branch(client, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _approved_po(db_session, branch, vendor, product, unit_price='11.20', vat_rate='12.00', qty=10):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number='PO-GRNI-0001', order_date=date(2026, 7, 21),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description=product.name,
                                           product_id=product.id, quantity=Decimal(str(qty)),
                                           unit_price=Decimal(unit_price), vat_rate=Decimal(vat_rate),
                                           amount=Decimal(unit_price) * qty))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _approved_and_posted_rr(db_session, branch, po, admin_user, received=10, number='RR-GRNI-0001'):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 21),
                         purchase_order_id=po.id, vendor_id=po.vendor_id,
                         vendor_name=po.vendor_name, status='approved')
    rr.line_items.append(ReceivingReportItem(line_number=1,
                                             purchase_order_item_id=po.line_items[0].id,
                                             product_id=po.line_items[0].product_id,
                                             received_quantity=Decimal(str(received))))
    db_session.add(rr); db_session.commit()
    post_rr_receipt(rr, admin_user)
    db_session.commit()
    return rr


def _bill_payload(vendor, rr, rr_item, decoy_account_id, unit_price, quantity):
    return {
        'ap_number': 'AP-GRNI-1', 'ap_date': date.today().isoformat(), 'due_date': date.today().isoformat(),
        'vendor_id': vendor.id, 'payment_terms': 'Net 30', 'notes': 'GRNI test bill',
        'line_items': json.dumps([{
            'description': 'Billed', 'amount': float(Decimal(str(unit_price)) * Decimal(str(quantity))),
            'vat_category': 'VAT12', 'account_id': decoy_account_id,   # decoy -- must be IGNORED server-side
            'quantity': quantity, 'unit_price': unit_price,
            'product_id': rr_item.product_id, 'source_rr_item_id': rr_item.id,
        }]),
        'vat_override': '0', 'vat_override_value': '0', 'wt_override': '0', 'wt_override_value': '0',
        'source_rr_ids': json.dumps([rr.id]),
    }


def test_tracked_rr_line_bills_to_grni_not_decoy_account(
        client, db_session, admin_user, branch_main, product_tracked, vl_vendor, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    decoy = make_account('61099')  # a plain expense account -- the client "picks" this, must be ignored
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    _seed_je_accounts(db_session)
    vendor = make_vendor(db_session, code='GRNIV1')
    login(client, 'admin', 'admin123'); _select_branch(client, branch_main)
    po = _approved_po(db_session, branch_main, vendor, product_tracked)
    rr = _approved_and_posted_rr(db_session, branch_main, po, admin_user)
    rr_item = rr.line_items[0]

    resp = client.post('/accounts-payable/create',
                       data=_bill_payload(vendor, rr, rr_item, decoy.id, '11.20', 10),
                       follow_redirects=True)
    assert resp.status_code == 200

    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    ap = AccountsPayable.query.filter_by(ap_number='AP-GRNI-1').first()
    assert ap is not None
    item = ap.line_items[0]
    assert item.account_id != decoy.id
    assert item.account.code == '2015'   # GRNI, not the decoy expense account


def test_exact_match_billing_needs_no_variance_account(
        client, db_session, admin_user, branch_main, product_tracked, vl_vendor, make_account):
    """Billed price exactly matches accrued -- inventory_variance is deliberately
    left UNASSIGNED and the bill must still post successfully (zero variance
    never needs the account resolved)."""
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    _seed_je_accounts(db_session)
    vendor = make_vendor(db_session, code='GRNIV2')
    login(client, 'admin', 'admin123'); _select_branch(client, branch_main)
    po = _approved_po(db_session, branch_main, vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _approved_and_posted_rr(db_session, branch_main, po, admin_user, received=10, number='RR-GRNI-2')
    rr_item = rr.line_items[0]

    payload = _bill_payload(vendor, rr, rr_item, make_account('61099').id, '11.20', 10)
    payload['ap_number'] = 'AP-GRNI-2'
    resp = client.post('/accounts-payable/create', data=payload, follow_redirects=True)
    assert resp.status_code == 200

    from app.accounts_payable.models import AccountsPayable
    ap = AccountsPayable.query.filter_by(ap_number='AP-GRNI-2').first()
    codes_with_amounts = {(l.account.code, l.debit_amount, l.credit_amount) for l in ap.journal_entry.lines}
    assert ('2015', Decimal('100.00'), Decimal('0.00')) in codes_with_amounts  # Dr GRNI = accrued net (10 * 10.00)
    assert not any(c == '61099' for c, _, _ in codes_with_amounts)  # variance NOT touched, none resolved/needed


def test_billed_more_than_accrued_debits_variance(
        client, db_session, admin_user, branch_main, product_tracked, vl_vendor, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    _assign('inventory_variance_account_code', '61050', make_account)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    _seed_je_accounts(db_session)
    vendor = make_vendor(db_session, code='GRNIV3')
    login(client, 'admin', 'admin123'); _select_branch(client, branch_main)
    po = _approved_po(db_session, branch_main, vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _approved_and_posted_rr(db_session, branch_main, po, admin_user, received=10, number='RR-GRNI-3')
    rr_item = rr.line_items[0]
    # accrued net = 10 * 10.00 = 100.00; billed at 12.32 gross/unit (net 11.00) -> billed net = 110.00
    payload = _bill_payload(vendor, rr, rr_item, make_account('61099').id, '12.32', 10)
    payload['ap_number'] = 'AP-GRNI-3'
    resp = client.post('/accounts-payable/create', data=payload, follow_redirects=True)
    assert resp.status_code == 200

    from app.accounts_payable.models import AccountsPayable
    ap = AccountsPayable.query.filter_by(ap_number='AP-GRNI-3').first()
    codes_with_amounts = {(l.account.code, l.debit_amount, l.credit_amount) for l in ap.journal_entry.lines}
    assert ('2015', Decimal('100.00'), Decimal('0.00')) in codes_with_amounts   # Dr GRNI, still the accrued amount
    assert ('61050', Decimal('10.00'), Decimal('0.00')) in codes_with_amounts   # Dr variance = 110.00 - 100.00
    assert ap.journal_entry.is_balanced


def test_billed_less_than_accrued_credits_variance(
        client, db_session, admin_user, branch_main, product_tracked, vl_vendor, make_account):
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    _assign('inventory_variance_account_code', '61050', make_account)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    _seed_je_accounts(db_session)
    vendor = make_vendor(db_session, code='GRNIV4')
    login(client, 'admin', 'admin123'); _select_branch(client, branch_main)
    po = _approved_po(db_session, branch_main, vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _approved_and_posted_rr(db_session, branch_main, po, admin_user, received=10, number='RR-GRNI-4')
    rr_item = rr.line_items[0]
    # billed at 10.08 gross/unit (net 9.00) -> billed net = 90.00, accrued = 100.00
    payload = _bill_payload(vendor, rr, rr_item, make_account('61099').id, '10.08', 10)
    payload['ap_number'] = 'AP-GRNI-4'
    resp = client.post('/accounts-payable/create', data=payload, follow_redirects=True)
    assert resp.status_code == 200

    from app.accounts_payable.models import AccountsPayable
    ap = AccountsPayable.query.filter_by(ap_number='AP-GRNI-4').first()
    codes_with_amounts = {(l.account.code, l.debit_amount, l.credit_amount) for l in ap.journal_entry.lines}
    assert ('2015', Decimal('100.00'), Decimal('0.00')) in codes_with_amounts   # Dr GRNI, still the accrued amount
    assert ('61050', Decimal('0.00'), Decimal('10.00')) in codes_with_amounts   # Cr variance = 100.00 - 90.00
    assert ap.journal_entry.is_balanced
