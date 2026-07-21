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


# ---------------------------------------------------------------------------
# Residual absorption must NEVER land on a GRNI-accrued leg.
#
# The pre-existing header-level residual absorber in _post_ap_je adds any
# rounding / VAT-override difference to whichever JE line is first_expense_line.
# A single clean line ALWAYS balances by construction (net_base == line_total -
# vat_amount, and the input-VAT bucket reconciles exactly to ap.vat_amount), so
# the only way a genuine nonzero residual arises is a header-level VAT override
# whose value differs from the sum of the per-line auto-extracted VAT -- exactly
# the case the absorber's own comment ("and any VAT override difference") exists
# for. These two tests exercise that real residual against a GRNI bill:
#   residual = sum(per-line auto VAT) - vat_override_value
# With one GRNI line (net 100.00, auto VAT 12.00) + one plain expense line
# (net 50.00, auto VAT 6.00): auto VAT = 18.00. Overriding VAT to 17.99 makes
#   residual = 18.00 - 17.99 = +0.01
# which pre-fix was silently added to the GRNI debit (100.00 -> 100.01),
# breaking "GRNI clears exactly at accrued". Post-fix the GRNI leg is no longer
# eligible, so the residual lands on the plain expense leg instead.
# ---------------------------------------------------------------------------


def _grni_first_plus_expense_payload(vendor, rr, rr_item, expense_account_id, ap_number):
    """Two-line bill: a GRNI-accrued line FIRST, then a plain expense line.

    A VAT override (17.99 vs auto 18.00) forces a genuine +0.01 residual.
    """
    return {
        'ap_number': ap_number, 'ap_date': date.today().isoformat(), 'due_date': date.today().isoformat(),
        'vendor_id': vendor.id, 'payment_terms': 'Net 30', 'notes': 'GRNI residual test',
        'line_items': json.dumps([
            {   # line 1 -- GRNI-accrued (forced to grni account server-side); FIRST line
                'description': 'Billed (tracked)', 'amount': float(Decimal('11.20') * Decimal('10')),
                'vat_category': 'VAT12', 'account_id': expense_account_id,   # decoy, overridden to GRNI
                'quantity': 10, 'unit_price': '11.20',
                'product_id': rr_item.product_id, 'source_rr_item_id': rr_item.id,
            },
            {   # line 2 -- plain expense, amount-only, NO source (never GRNI)
                'description': 'Freight', 'amount': 56.00,
                'vat_category': 'VAT12', 'account_id': expense_account_id,
                'wt_id': None, 'wt_rate': None,
            },
        ]),
        # VAT override: 17.99 vs auto-extracted 18.00 -> +0.01 residual
        'vat_override': '1', 'vat_override_value': '17.99',
        'wt_override': '0', 'wt_override_value': '0',
        'source_rr_ids': json.dumps([rr.id]),
    }


def test_vat_override_residual_never_lands_on_grni_leg(
        client, db_session, admin_user, branch_main, product_tracked, vl_vendor, make_account):
    """A GRNI-first bill with a genuine header residual: the GRNI leg must debit
    EXACTLY the accrued amount, and the +0.01 residual must land on the plain
    expense leg -- not be silently absorbed into GRNI. FAILS against pre-fix
    code (which set GRNI to 100.01)."""
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    exp = _seed_je_accounts(db_session)   # 61001 Rent Expense (leaf, postable)
    vendor = make_vendor(db_session, code='GRNIV5')
    login(client, 'admin', 'admin123'); _select_branch(client, branch_main)
    po = _approved_po(db_session, branch_main, vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _approved_and_posted_rr(db_session, branch_main, po, admin_user, received=10, number='RR-GRNI-5')
    rr_item = rr.line_items[0]

    payload = _grni_first_plus_expense_payload(vendor, rr, rr_item, exp.id, 'AP-GRNI-5')
    resp = client.post('/accounts-payable/create', data=payload, follow_redirects=True)
    assert resp.status_code == 200

    from app.accounts_payable.models import AccountsPayable
    ap = AccountsPayable.query.filter_by(ap_number='AP-GRNI-5').first()
    assert ap is not None and ap.journal_entry is not None
    lines = ap.journal_entry.lines

    grni_legs = [l for l in lines if l.account.code == '2015']
    assert len(grni_legs) == 1
    # THE INVARIANT: GRNI debits EXACTLY the accrued amount (100.00), NOT 100.01.
    assert grni_legs[0].debit_amount == Decimal('100.00')

    # The +0.01 residual instead lands on the plain expense (61001) leg: 50.00 + 0.01.
    exp_legs = [l for l in lines if l.account.code == '61001']
    assert len(exp_legs) == 1
    assert exp_legs[0].debit_amount == Decimal('50.01')

    assert ap.journal_entry.is_balanced


def _all_grni_with_residual_payload(vendor, rr, rr_item, decoy_account_id, ap_number):
    """Single GRNI-accrued line + a VAT override that forces a nonzero residual."""
    return {
        'ap_number': ap_number, 'ap_date': date.today().isoformat(), 'due_date': date.today().isoformat(),
        'vendor_id': vendor.id, 'payment_terms': 'Net 30', 'notes': 'all-GRNI residual test',
        'line_items': json.dumps([{
            'description': 'Billed (tracked)', 'amount': float(Decimal('11.20') * Decimal('10')),
            'vat_category': 'VAT12', 'account_id': decoy_account_id,
            'quantity': 10, 'unit_price': '11.20',
            'product_id': rr_item.product_id, 'source_rr_item_id': rr_item.id,
        }]),
        # auto VAT = 12.00; override to 11.99 -> +0.01 residual with no non-GRNI
        # leg to absorb it -> JE cannot balance -> _post_ap_je raises (fail-closed).
        'vat_override': '1', 'vat_override_value': '11.99',
        'wt_override': '0', 'wt_override_value': '0',
        'source_rr_ids': json.dumps([rr.id]),
    }


def test_all_grni_bill_with_residual_fails_closed_not_absorbed(
        client, db_session, admin_user, branch_main, product_tracked, vl_vendor, make_account):
    """When a bill is ENTIRELY GRNI-accrued lines and has a genuine residual,
    there is no eligible first_expense_line, so the residual is NOT absorbed:
    the JE fails is_balanced and _post_ap_je raises. The route catches it, rolls
    back, and no bill is persisted -- the correct fail-closed behavior (raise,
    never corrupt the accrual leg)."""
    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    _seed_je_accounts(db_session)
    vendor = make_vendor(db_session, code='GRNIV6')
    login(client, 'admin', 'admin123'); _select_branch(client, branch_main)
    po = _approved_po(db_session, branch_main, vendor, product_tracked, unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _approved_and_posted_rr(db_session, branch_main, po, admin_user, received=10, number='RR-GRNI-6')
    rr_item = rr.line_items[0]

    payload = _all_grni_with_residual_payload(vendor, rr, rr_item, make_account('61099').id, 'AP-GRNI-6')
    resp = client.post('/accounts-payable/create', data=payload, follow_redirects=True)
    assert resp.status_code == 200

    from app.accounts_payable.models import AccountsPayable
    # Fail-closed: the bill was rolled back, nothing persisted, GRNI never corrupted.
    assert AccountsPayable.query.filter_by(ap_number='AP-GRNI-6').first() is None
