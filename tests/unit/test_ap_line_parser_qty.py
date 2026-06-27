"""Unit tests for the AP line parser: qty / uom_text / unit_price / product_id fields."""
import json
from decimal import Decimal
from app.accounts_payable.models import AccountsPayable


def test_ap_line_qty_price_derives_amount(db_session, main_branch):
    """Parser reads quantity + unit_price and calculate_amounts() derives amount = qty × price."""
    from app.accounts_payable.views import _parse_and_attach_line_items

    ap = AccountsPayable(branch_id=main_branch.id)
    payload = json.dumps([{
        'description': 'Parts',
        'quantity': '4',
        'unit_price': '56.00',
        'uom_id': None,
        'uom_text': 'set',
        'product_id': None,
        'vat_category': None,
        'account_id': None,
    }])
    _parse_and_attach_line_items(ap, payload)
    line = ap.line_items[0]
    assert line.quantity == Decimal('4')
    assert line.amount == Decimal('224.00')
    assert line.uom_text == 'set'


def test_ap_line_parser_null_qty_keeps_explicit_amount(db_session, main_branch):
    """When quantity/unit_price are null, amount stays as the explicit value."""
    from app.accounts_payable.views import _parse_and_attach_line_items

    ap = AccountsPayable(branch_id=main_branch.id)
    payload = json.dumps([{
        'description': 'Service fee',
        'quantity': None,
        'unit_price': None,
        'uom_id': None,
        'uom_text': '',
        'product_id': None,
        'vat_category': None,
        'account_id': None,
        'amount': '500.00',
    }])
    _parse_and_attach_line_items(ap, payload)
    line = ap.line_items[0]
    assert line.quantity is None
    assert line.unit_price is None
    assert line.amount == Decimal('500.00')


def test_ap_line_parser_malformed_payload_is_guarded(db_session, main_branch):
    """Malformed JSON is handled gracefully — no items attached."""
    from app.accounts_payable.views import _parse_and_attach_line_items

    ap = AccountsPayable(branch_id=main_branch.id)
    _parse_and_attach_line_items(ap, 'NOT_VALID_JSON')
    assert len(ap.line_items) == 0
