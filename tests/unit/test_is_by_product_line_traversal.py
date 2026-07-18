from decimal import Decimal
import pytest
from app.reports.income_statement_by_product_line import _resolve_leaves

pytestmark = [pytest.mark.unit]


def test_leaf_with_children_uses_child_amounts():
    lines = [{'code': '502', 'name': 'Cost of Sales', 'account_id': 1, 'total': 150.0,
             'children': [{'code': '50201', 'name': 'Materials', 'account_id': 2, 'amount': 100.0},
                          {'code': '50202', 'name': 'Labor', 'account_id': 3, 'amount': 50.0}]}]
    leaves = _resolve_leaves(lines)
    assert leaves == [{'account_id': 2, 'amount': Decimal('100.0')},
                      {'account_id': 3, 'amount': Decimal('50.0')}]


def test_leaf_with_no_children_uses_own_total():
    lines = [{'code': '50301', 'name': 'Interest Expense', 'account_id': 9, 'total': 20.0,
             'children': []}]
    leaves = _resolve_leaves(lines)
    assert leaves == [{'account_id': 9, 'amount': Decimal('20.0')}]


def test_mixed_groups():
    lines = [
        {'code': '502', 'name': 'Group', 'account_id': 1, 'total': 100.0,
         'children': [{'code': '50201', 'name': 'A', 'account_id': 2, 'amount': 100.0}]},
        {'code': '504', 'name': 'Standalone', 'account_id': 5, 'total': 30.0, 'children': []},
    ]
    leaves = _resolve_leaves(lines)
    assert leaves == [{'account_id': 2, 'amount': Decimal('100.0')},
                      {'account_id': 5, 'amount': Decimal('30.0')}]


def test_empty_section():
    assert _resolve_leaves([]) == []
