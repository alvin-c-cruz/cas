import pytest
from app.reports.two_column import merge_is_two_column, merge_cf_two_column, _union_by

pytestmark = [pytest.mark.unit]


def _cf(op_total, wc_amt, net_change, cash_begin, cash_end):
    return {
        'period_start': None, 'period_end': None, 'method': 'indirect',
        'operating': {'net_income': op_total, 'depreciation': 0.0,
                      'working_capital': [{'name': 'Increase in AR', 'amount': wc_amt}],
                      'total': op_total},
        'investing': {'lines': [], 'total': 0.0},
        'financing': {'lines': [], 'total': 0.0},
        'net_change': net_change, 'cash_begin': cash_begin, 'cash_end': cash_end,
        'is_reconciled': True, 'difference': 0.0,
    }


def test_merge_cf_pairs_scalars_and_unions_lines():
    merged = merge_cf_two_column(_cf(60.0, -10.0, 60.0, 0.0, 60.0),
                                 _cf(420.0, -70.0, 420.0, 0.0, 420.0))
    assert merged['net_change'] == {'mtd': 60.0, 'ytd': 420.0}
    assert merged['cash_end'] == {'mtd': 60.0, 'ytd': 420.0}
    assert merged['operating']['total'] == {'mtd': 60.0, 'ytd': 420.0}
    wc = merged['operating']['working_capital'][0]
    assert wc['name'] == 'Increase in AR' and wc['mtd_amount'] == -10.0 and wc['ytd_amount'] == -70.0


def _is(section_total, line_total, net):
    return {
        'period_start': None, 'period_end': None,
        'sections': [{
            'key': 'revenue', 'label': 'Sales', 'sign': 1, 'total': section_total,
            'lines': [{'code': '40001', 'name': 'Sales', 'account_id': 1,
                       'total': line_total, 'children': []}],
        }, {
            'key': 'income_tax', 'label': 'Income Tax Expense', 'sign': -1, 'total': 0.0,
            'lines': [], 'subtotal_label': 'Net Income', 'subtotal': net,
        }],
        'net_sales': section_total, 'gross_profit': section_total,
        'operating_income': net, 'income_before_tax': net, 'net_income': net,
    }


def test_merge_carries_both_column_totals():
    merged = merge_is_two_column(_is(100.0, 100.0, 60.0), _is(700.0, 700.0, 420.0))
    rev = merged['sections'][0]
    assert rev['mtd_total'] == 100.0 and rev['ytd_total'] == 700.0
    line = rev['lines'][0]
    assert line['mtd_amount'] == 100.0 and line['ytd_amount'] == 700.0


def test_merge_carries_subtotal_and_scalar_pairs():
    merged = merge_is_two_column(_is(100.0, 100.0, 60.0), _is(700.0, 700.0, 420.0))
    tax = merged['sections'][1]
    assert tax['mtd_subtotal'] == 60.0 and tax['ytd_subtotal'] == 420.0
    assert merged['net_income'] == {'mtd': 60.0, 'ytd': 420.0}


def test_merge_zero_fills_line_present_in_one_column_only():
    mtd = _is(0.0, 0.0, 0.0)
    mtd['sections'][0]['lines'] = []          # no line this month
    ytd = _is(700.0, 700.0, 420.0)            # line YTD only
    merged = merge_is_two_column(mtd, ytd)
    line = merged['sections'][0]['lines'][0]
    assert line['mtd_amount'] == 0.0 and line['ytd_amount'] == 700.0


def test_union_by_preserves_order_and_zero_fills():
    a = [{'code': 'x', 'total': 1.0}]
    b = [{'code': 'y', 'total': 2.0}]
    out = _union_by(a, b, key='code', a_field='total', b_field='total')
    assert [(o['code'], o['mtd'], o['ytd']) for o in out] == [('x', 1.0, 0.0), ('y', 0.0, 2.0)]
