"""Unit tests for the PurchaseOrder model + PO-#### numbering (operational, posts no JE)."""
from decimal import Decimal
from app.purchase_orders.models import (
    PurchaseOrder, PurchaseOrderItem, generate_po_number, next_po_number_for,
    VAT_TREATMENTS,
)
import pytest

pytestmark = [pytest.mark.purchase_orders]


def test_vat_treatments_constant():
    assert VAT_TREATMENTS == ('inclusive', 'exclusive', 'zero_rated')


def test_generate_po_number_first_of_month(db_session):
    n = generate_po_number()
    assert n == '00001'


def test_generate_po_number_increments(db_session):
    n1 = generate_po_number()
    po = PurchaseOrder(po_number=n1, order_date=None, status='draft')
    db_session.add(po)
    db_session.commit()
    assert generate_po_number() == '00002'


def test_generate_po_number_continues_from_legacy_literal_number(db_session):
    po = PurchaseOrder(po_number='30500', order_date=None, status='draft')
    db_session.add(po)
    db_session.commit()
    assert generate_po_number() == '30501'


def test_generate_po_number_ignores_legacy_prefixed_numbers(db_session):
    po = PurchaseOrder(po_number='PO-2026-07-0030', order_date=None, status='draft')
    db_session.add(po)
    db_session.commit()
    assert generate_po_number() == '00001'


# --- next_po_number_for: per-purchaser suggestion -------------------------
# PhilGen's two purchasers each hold their OWN pre-printed PO pad, and the two
# pads' number ranges NEVER overlap. A global max() is therefore not merely
# unhelpful -- it is guaranteed to point outside the other purchaser's pad.


def _po(number, user_id):
    return PurchaseOrder(po_number=number, order_date=None, status='draft',
                         created_by_id=user_id)


def test_next_po_number_fallback_is_branch_scoped_under_branch_scope(
        db_session, admin_user, main_branch, branch_manila):
    """A purchaser with no pad falls back to the company's numbering POLICY,
    which under branch scope means this branch's own series."""
    from app.settings import AppSettings
    AppSettings.set_setting('document_number_scope', 'branch')
    db_session.add_all([
        PurchaseOrder(po_number='30500', order_date=None, status='draft',
                      branch_id=main_branch.id),
        PurchaseOrder(po_number='90000', order_date=None, status='draft',
                      branch_id=branch_manila.id),
    ])
    db_session.commit()
    assert next_po_number_for(admin_user.id, main_branch.id) == '30501'


def test_next_po_number_still_ignores_branch_when_the_purchaser_has_a_pad(
        db_session, admin_user, accountant_user, main_branch, branch_manila):
    """CONTROL -- person beats branch. Even under branch scope, a purchaser
    holding a pad gets HER next number; splitting one physical pad across two
    branches would be a regression wearing a feature's clothes."""
    from app.settings import AppSettings
    AppSettings.set_setting('document_number_scope', 'branch')
    po_a = _po('00042E', admin_user.id); po_a.branch_id = main_branch.id
    po_b = _po('70011F', accountant_user.id); po_b.branch_id = branch_manila.id
    db_session.add_all([po_a, po_b])
    db_session.commit()
    assert next_po_number_for(admin_user.id, main_branch.id) == '00043E'
    assert next_po_number_for(admin_user.id, branch_manila.id) == '00043E'


def test_next_po_number_is_per_purchaser(db_session, admin_user, accountant_user):
    """The headline case: two pads, non-overlapping ranges, each gets her own."""
    db_session.add_all([_po('00042E', admin_user.id), _po('70011F', accountant_user.id)])
    db_session.commit()
    assert next_po_number_for(admin_user.id) == '00043E'
    assert next_po_number_for(accountant_user.id) == '70012F'


def test_next_po_number_preserves_the_suffix(db_session, admin_user):
    db_session.add(_po('00001E', admin_user.id))
    db_session.commit()
    assert next_po_number_for(admin_user.id) == '00002E'


def test_next_po_number_preserves_zero_padded_width(db_session, admin_user):
    db_session.add(_po('00099E', admin_user.id))
    db_session.commit()
    assert next_po_number_for(admin_user.id) == '00100E'


def test_next_po_number_width_grows_on_overflow(db_session, admin_user):
    db_session.add(_po('99999E', admin_user.id))
    db_session.commit()
    assert next_po_number_for(admin_user.id) == '100000E'


def test_next_po_number_picks_the_highest_by_numeric_value(db_session, admin_user):
    """'9E' > '10E' as a STRING; the digit part is compared as a NUMBER."""
    db_session.add_all([_po('00009E', admin_user.id), _po('00010E', admin_user.id)])
    db_session.commit()
    assert next_po_number_for(admin_user.id) == '00011E'


def test_next_po_number_falls_back_when_purchaser_has_no_prior_po(
        db_session, admin_user, accountant_user):
    """A purchaser's very first entry has nothing to infer from -- fall back to
    the global generator (the field is typed off the paper form anyway).

    The other purchaser's number is deliberately PURELY NUMERIC so the global
    generator returns something other than its '00001' empty-DB default -- a
    fallback that merely hardcoded '00001' would otherwise pass this."""
    db_session.add(_po('30500', admin_user.id))
    db_session.commit()
    assert next_po_number_for(accountant_user.id) == '30501' == generate_po_number()


def test_next_po_number_ignores_legacy_prefixed_numbers(db_session, admin_user):
    db_session.add(_po('PO-2026-07-0030', admin_user.id))
    db_session.commit()
    assert next_po_number_for(admin_user.id) == generate_po_number() == '00001'


def test_next_po_number_ignores_other_purchasers_higher_range(
        db_session, admin_user, accountant_user):
    """Control on the defect itself: the OTHER pad's higher number must not
    leak into this purchaser's suggestion."""
    db_session.add_all([_po('00007E', admin_user.id), _po('90000F', accountant_user.id)])
    db_session.commit()
    assert next_po_number_for(admin_user.id) == '00008E'


def test_next_po_number_unpadded_number_stays_unpadded(db_session, admin_user):
    db_session.add(_po('30500', admin_user.id))
    db_session.commit()
    assert next_po_number_for(admin_user.id) == '30501'


def test_line_amounts_inclusive_extracts_vat(db_session):
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('2'),
                           unit_price=Decimal('56'), vat_category='V12', vat_rate=Decimal('12'))
    li.calculate_amounts()
    assert li.amount == Decimal('112.00')          # 2 x 56, VAT-inclusive
    assert li.vat_amount == Decimal('12.00')       # 112 - 112/1.12
    assert li.line_total == Decimal('112.00')      # line_total = the inclusive amount (mirror SO)
    assert li.amount - li.vat_amount == Decimal('100.00')  # net-of-VAT


def test_totals_inclusive_extracts(db_session):
    po = PurchaseOrder(po_number=generate_po_number(), status='draft', vat_treatment='inclusive')
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('1'),
                           unit_price=Decimal('112'), vat_category='V12', vat_rate=Decimal('12'))
    li.calculate_amounts()
    po.line_items.append(li)
    po.calculate_totals()
    assert po.subtotal == Decimal('112.00')
    assert po.vat_amount == Decimal('12.00')
    assert po.total_amount == Decimal('112.00')


def test_totals_exclusive_adds_vat(db_session):
    po = PurchaseOrder(po_number=generate_po_number(), status='draft', vat_treatment='exclusive')
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('1'),
                           unit_price=Decimal('100'), vat_category='V12', vat_rate=Decimal('12'))
    li.calculate_amounts()
    po.line_items.append(li)
    po.calculate_totals()
    assert po.vat_amount == Decimal('12.00')
    assert po.total_amount == Decimal('112.00')


def test_totals_zero_rated(db_session):
    po = PurchaseOrder(po_number=generate_po_number(), status='draft', vat_treatment='zero_rated')
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('1'),
                           unit_price=Decimal('100'), vat_category='V0', vat_rate=Decimal('0'))
    li.calculate_amounts()
    po.line_items.append(li)
    po.calculate_totals()
    assert po.vat_amount == Decimal('0.00')
    assert po.total_amount == Decimal('100.00')


def test_received_billed_default_zero(db_session):
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('5'), unit_price=Decimal('10'))
    assert (li.received_quantity or 0) == 0
    assert (li.billed_quantity or 0) == 0
