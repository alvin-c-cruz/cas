# tests/work_orders/test_consumption_reversal.py
from collections import Counter
from decimal import Decimal
import pytest
from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.bill_of_materials.service import consume_materials
from app.work_orders.models import WorkOrder
from app.work_orders.service import release_work_order
from app.work_orders.forms import generate_wo_number
from app.products.models import Product
from app.stock_adjustments.models import StockBalance
from app.stock_adjustments.service import post_movement
from app.settings import AppSettings
from app.journal_entries.models import JournalEntry
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def _assign(code_setting, code, account_factory):
    account_factory(code)
    AppSettings.set_setting(code_setting, code, updated_by='test')


def _wo_with_two_materials(main_branch, out_code='RCN-OUT', c1='RCN-C1', c2='RCN-C2'):
    out = Product(code=out_code, name='Out', is_active=True)
    comp1 = Product(code=c1, name='Comp A', is_active=True, track_inventory=True, costing_method='moving_average')
    comp2 = Product(code=c2, name='Comp B', is_active=True, track_inventory=True, costing_method='moving_average')
    db.session.add_all([out, comp1, comp2]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp1.id, quantity_per=Decimal('1')))
    bom.lines.append(BillOfMaterialLine(line_number=2, component_product_id=comp2.id, quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id, qty_to_produce=Decimal('10'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None); db.session.commit()
    return wo, comp1, comp2


def test_reverse_consumption_noop_when_never_issued(db_session, main_branch, admin_user):
    from app.work_orders.service import reverse_consumption
    wo, _, _ = _wo_with_two_materials(main_branch)
    reverse_consumption(wo, admin_user)
    db.session.commit()
    assert JournalEntry.query.filter_by(reference=wo.wo_number).count() == 0


def test_reverse_consumption_reverses_single_issue(db_session, main_branch, admin_user, make_account):
    from app.work_orders.service import reverse_consumption
    _assign('inventory_account_code', '1401', make_account)
    _assign('wip_account_code', '1402', make_account)
    wo, comp1, comp2 = _wo_with_two_materials(main_branch)
    post_movement(comp1, main_branch.id, 'receipt', Decimal('20'), Decimal('2.00'), 'seed', None, 's', admin_user)
    db.session.commit()
    mat1 = next(m for m in wo.materials if m.component_product_id == comp1.id)
    consume_materials(wo, [(mat1, Decimal('4'))], admin_user)
    db.session.commit()

    reverse_consumption(wo, admin_user)
    db.session.commit()

    bal = StockBalance.query.filter_by(product_id=comp1.id, branch_id=main_branch.id).one()
    assert bal.quantity_on_hand == Decimal('20.0000')   # back to the seeded 20
    jes = JournalEntry.query.filter_by(reference=wo.wo_number).order_by(JournalEntry.id).all()
    assert len(jes) == 2   # original + reversal

    original, reversal = jes[0], jes[1]
    original_wip_line = next(l for l in original.lines if l.debit_amount > 0)   # WIP was debited originally
    original_inv_line = next(l for l in original.lines if l.credit_amount > 0)  # Inventory was credited originally
    reversal_wip_line = next(l for l in reversal.lines if l.account_id == original_wip_line.account_id)
    reversal_inv_line = next(l for l in reversal.lines if l.account_id == original_inv_line.account_id)
    assert reversal_wip_line.credit_amount == original_wip_line.debit_amount   # WIP flips to credit
    assert reversal_wip_line.debit_amount == Decimal('0')
    assert reversal_inv_line.debit_amount == original_inv_line.credit_amount  # Inventory flips to debit
    assert reversal_inv_line.credit_amount == Decimal('0')


def test_reverse_consumption_reverses_multiple_separate_issue_events(db_session, main_branch, admin_user, make_account):
    from app.work_orders.service import reverse_consumption
    _assign('inventory_account_code', '1401', make_account)
    _assign('wip_account_code', '1402', make_account)
    wo, comp1, comp2 = _wo_with_two_materials(main_branch)
    post_movement(comp1, main_branch.id, 'receipt', Decimal('20'), Decimal('2.00'), 'seed', None, 's', admin_user)
    post_movement(comp2, main_branch.id, 'receipt', Decimal('20'), Decimal('3.00'), 'seed', None, 's', admin_user)
    db.session.commit()
    mat1 = next(m for m in wo.materials if m.component_product_id == comp1.id)
    mat2 = next(m for m in wo.materials if m.component_product_id == comp2.id)
    # two SEPARATE issue events, each its own consume_materials call/JE
    consume_materials(wo, [(mat1, Decimal('4'))], admin_user)
    db.session.commit()
    consume_materials(wo, [(mat2, Decimal('2'))], admin_user)
    db.session.commit()
    assert JournalEntry.query.filter_by(reference=wo.wo_number).count() == 2   # two original JEs

    reverse_consumption(wo, admin_user)
    db.session.commit()

    bal1 = StockBalance.query.filter_by(product_id=comp1.id, branch_id=main_branch.id).one()
    bal2 = StockBalance.query.filter_by(product_id=comp2.id, branch_id=main_branch.id).one()
    assert bal1.quantity_on_hand == Decimal('20.0000')
    assert bal2.quantity_on_hand == Decimal('20.0000')
    jes = JournalEntry.query.filter_by(reference=wo.wo_number).order_by(JournalEntry.id).all()
    assert len(jes) == 3   # 2 originals + 1 combined reversal
    reversal_je = jes[-1]
    assert reversal_je.is_balanced
    assert reversal_je.lines.count() == 4   # 2 lines from each of the 2 originals (lines is lazy='dynamic')

    # Each of the two originals' lines must have a correctly Dr/Cr-swapped, same-amount
    # counterpart in the single combined reversal JE (4 lines total, 2 swapped pairs).
    # Match as a multiset of (account_id, expected_debit, expected_credit) rather than by
    # account_id alone -- both originals post to the SAME wip/inventory control accounts,
    # just with different amounts (comp1's 4 units @ 2.00 vs comp2's 2 units @ 3.00).
    original1, original2 = jes[0], jes[1]
    expected_swapped = Counter(
        (line.account_id, line.credit_amount, line.debit_amount)   # (account_id, expected debit, expected credit)
        for orig in (original1, original2)
        for line in orig.lines
    )
    actual_reversal = Counter(
        (l.account_id, l.debit_amount, l.credit_amount)
        for l in reversal_je.lines
    )
    assert actual_reversal == expected_swapped


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_cancel_route_reverses_consumption_when_materials_issued(
        client, db_session, admin_user, main_branch, make_account):
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db.session.commit(); clear_module_config_cache()
    _assign('inventory_account_code', '1401', make_account)
    _assign('wip_account_code', '1402', make_account)
    wo, comp1, _ = _wo_with_two_materials(main_branch)
    post_movement(comp1, main_branch.id, 'receipt', Decimal('20'), Decimal('2.00'), 'seed', None, 's', admin_user)
    db.session.commit()
    mat1 = next(m for m in wo.materials if m.component_product_id == comp1.id)
    consume_materials(wo, [(mat1, Decimal('4'))], admin_user)
    db.session.commit()
    _login(client, admin_user, main_branch)

    resp = client.post(f'/work-orders/{wo.id}/cancel',
                       data={'cancel_reason': 'Customer changed the order'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(wo)
    assert wo.status == 'cancelled'
    bal = StockBalance.query.filter_by(product_id=comp1.id, branch_id=main_branch.id).one()
    assert bal.quantity_on_hand == Decimal('20.0000')


def test_cancel_route_noop_when_never_issued(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db.session.commit(); clear_module_config_cache()
    wo, _, _ = _wo_with_two_materials(main_branch)
    _login(client, admin_user, main_branch)

    resp = client.post(f'/work-orders/{wo.id}/cancel',
                       data={'cancel_reason': 'Never started production'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(wo)
    assert wo.status == 'cancelled'
    assert JournalEntry.query.filter_by(reference=wo.wo_number).count() == 0


def test_issue_material_route_flashes_negative_on_hand_warning(
        client, db_session, admin_user, main_branch, make_account):
    """Issuing material for a component with NO prior stock drives it negative
    -- consume_materials() sets wo._negative_warnings, and the route must read
    it and flash a warning alongside the success flash (mirrors the
    delivery_receipts/stock_adjustments pattern)."""
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db.session.commit(); clear_module_config_cache()
    _assign('inventory_account_code', '1401', make_account)
    _assign('wip_account_code', '1402', make_account)
    wo, comp1, _ = _wo_with_two_materials(main_branch)
    # comp1 has NO prior stock seeded -- issuing any quantity drives it negative.
    mat1 = next(m for m in wo.materials if m.component_product_id == comp1.id)
    _login(client, admin_user, main_branch)

    resp = client.post(f'/work-orders/{wo.id}/materials/{mat1.id}/issue',
                       data={'quantity': '4'},
                       follow_redirects=True)

    assert resp.status_code == 200
    assert b'negative' in resp.data
    assert comp1.code.encode() in resp.data
