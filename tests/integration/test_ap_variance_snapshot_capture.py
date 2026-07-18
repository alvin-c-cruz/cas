"""Regression tests for R-02 Phase 6: _build_validated_ap_lines() must derive
matched_unit_price/matched_quantity SERVER-SIDE from the source PO/RR line -- never
trusting a client-supplied value -- and leave all four columns NULL for a manual line."""
import json
from datetime import date
from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable


def _seed_accounts():
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Debit'),
        ('69903', 'Test Expense', 'Expense', 'Debit'),
    ]:
        db.session.add(Account(code=code, name=name, account_type=typ,
                               normal_balance=bal, is_active=True))
    db.session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db.session)
    return Account.query.filter_by(code='69903').first()


def _po(db_session, branch, vendor, qty=100, price=10):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number='PO-SNAP-0001', order_date=date(2026, 7, 18),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Subcontract',
                                           quantity=Decimal(str(qty)), unit_price=Decimal(str(price)),
                                           amount=Decimal(str(qty * price))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _rr(db_session, branch, po, received=60):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number='RR-SNAP-0001', receipt_date=date(2026, 7, 18),
                         purchase_order_id=po.id, vendor_id=po.vendor_id,
                         vendor_name=po.vendor_name, status='approved')
    rr.line_items.append(ReceivingReportItem(line_number=1,
                                             purchase_order_item_id=po.line_items[0].id,
                                             received_quantity=Decimal(str(received))))
    db_session.add(rr); db_session.commit()
    return rr


def _login_and_select_branch(client, user, branch):
    client.post('/login', data={'username': user.username, 'password': 'accountant123'},
                follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def test_direct_po_billing_snapshots_po_price_and_quantity(client, accountant_user, db_session,
                                                            main_branch, vl_vendor):
    exp = _seed_accounts()
    po = _po(db_session, main_branch, vl_vendor, qty=100, price=10)
    _login_and_select_branch(client, accountant_user, main_branch)

    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'AP-SNAP-0001', 'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'payee': f'vendor:{vl_vendor.id}', 'payment_terms': 'Net 30', 'notes': 'test',
        'line_items': json.dumps([{
            'description': 'Subcontract', 'amount': 800.0,
            'quantity': 80, 'unit_price': 10,  # billed LESS than the PO's 100 -- a real variance
            'account_id': exp.id, 'vat_category': None, 'wt_id': None, 'wt_rate': None,
            'source_po_item_id': po.line_items[0].id, 'source_rr_item_id': None,
        }]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=False)
    assert resp.status_code == 302, resp.data[:800]

    ap = AccountsPayable.query.filter_by(ap_number='AP-SNAP-0001').first()
    assert ap is not None
    line = ap.line_items[0]
    assert line.source_po_item_id == po.line_items[0].id
    assert line.source_rr_item_id is None
    assert line.matched_unit_price == Decimal('10.00')
    assert line.matched_quantity == Decimal('100.0000')
    assert line.quantity_variance == Decimal('-20.0000')   # 80 billed vs 100 matched
    assert line.price_variance is None                     # 10 billed == 10 matched


def test_rr_billing_snapshots_rr_quantity_and_po_price(client, accountant_user, db_session,
                                                        main_branch, vl_vendor):
    exp = _seed_accounts()
    po = _po(db_session, main_branch, vl_vendor, qty=100, price=10)
    rr = _rr(db_session, main_branch, po, received=60)
    _login_and_select_branch(client, accountant_user, main_branch)

    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'AP-SNAP-0002', 'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'payee': f'vendor:{vl_vendor.id}', 'payment_terms': 'Net 30', 'notes': 'test',
        'line_items': json.dumps([{
            'description': 'Goods', 'amount': 660.0,
            'quantity': 60, 'unit_price': 11,   # billed price 11 vs PO's 10 -- a real variance
            'account_id': exp.id, 'vat_category': None, 'wt_id': None, 'wt_rate': None,
            'source_po_item_id': None, 'source_rr_item_id': rr.line_items[0].id,
        }]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=False)
    assert resp.status_code == 302, resp.data[:800]

    ap = AccountsPayable.query.filter_by(ap_number='AP-SNAP-0002').first()
    line = ap.line_items[0]
    assert line.source_rr_item_id == rr.line_items[0].id
    assert line.source_po_item_id == po.line_items[0].id   # backfilled via the RR line's own FK
    assert line.matched_unit_price == Decimal('10.00')     # from the PO line, not the RR line
    assert line.matched_quantity == Decimal('60.0000')     # the RECEIVED quantity, not ordered 100
    assert line.price_variance == Decimal('1.00')          # 11 billed vs 10 matched
    assert line.quantity_variance is None                  # 60 billed == 60 received


def test_manual_line_gets_null_snapshot_even_if_client_sends_fake_matched_values(
        client, accountant_user, db_session, main_branch, vl_vendor):
    """The server must never trust a client-supplied matched_* value -- prove it by
    posting one anyway (as an attacker or a stale cached page might) and confirming
    it's ignored: with no source_*_item_id, matched_* stay NULL regardless."""
    exp = _seed_accounts()
    _login_and_select_branch(client, accountant_user, main_branch)

    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'AP-SNAP-0003', 'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'payee': f'vendor:{vl_vendor.id}', 'payment_terms': 'Net 30', 'notes': 'test',
        'line_items': json.dumps([{
            'description': 'Manual line', 'amount': 500.0,
            'account_id': exp.id, 'vat_category': None, 'wt_id': None, 'wt_rate': None,
            'source_po_item_id': None, 'source_rr_item_id': None,
            'matched_unit_price': 1.0, 'matched_quantity': 1.0,   # attacker-supplied, must be ignored
        }]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=False)
    assert resp.status_code == 302, resp.data[:800]

    ap = AccountsPayable.query.filter_by(ap_number='AP-SNAP-0003').first()
    line = ap.line_items[0]
    assert line.source_po_item_id is None
    assert line.source_rr_item_id is None
    assert line.matched_unit_price is None
    assert line.matched_quantity is None
    assert line.has_variance is False
