import pytest
from app.reports.statement_export import cash_flow_lines

pytestmark = [pytest.mark.unit]

CF = {
    'operating': {
        'net_income': 350.0, 'depreciation': 50.0,
        'working_capital': [{'name': '(Increase)/decrease in Accounts Receivable', 'amount': -300.0},
                            {'name': 'Increase/(decrease) in Accounts Payable', 'amount': 100.0}],
        'total': 200.0,
    },
    'investing': {'lines': [{'name': '(Acquisition)/disposal of Construction Equipment', 'amount': -500.0}],
                  'total': -500.0},
    'financing': {'lines': [{'name': 'Capital Stock', 'amount': 1000.0}], 'total': 1000.0},
    'net_change': 700.0, 'cash_begin': 0.0, 'cash_end': 700.0,
}


def test_lines_cover_all_sections_and_reconciliation():
    lines = cash_flow_lines(CF)
    labels = [ln['label'] for ln in lines]
    assert 'CASH FLOWS FROM OPERATING ACTIVITIES' in labels
    assert 'CASH FLOWS FROM INVESTING ACTIVITIES' in labels
    assert 'CASH FLOWS FROM FINANCING ACTIVITIES' in labels
    assert 'NET INCREASE/(DECREASE) IN CASH' in labels
    assert 'Cash at beginning of period' in labels
    assert 'Cash at end of period' in labels
    # net change carries a double-bottom rule
    net = next(ln for ln in lines if ln['label'] == 'NET INCREASE/(DECREASE) IN CASH')
    assert net['amount'] == 700.0 and net['rule'] == 'double_bottom'


def test_depreciation_line_omitted_when_zero():
    cf = {**CF, 'operating': {**CF['operating'], 'depreciation': 0.0}}
    labels = [ln['label'] for ln in cash_flow_lines(cf)]
    assert not any('Depreciation' in lbl for lbl in labels)


DIRECT_CF = {
    'method': 'direct',
    'operating': {'lines': [{'name': 'Cash received from customers', 'amount': 700.0},
                            {'name': 'Cash paid to suppliers', 'amount': -150.0}],
                  'total': 550.0},
    'investing': {'lines': [], 'total': 0.0},
    'financing': {'lines': [], 'total': 0.0},
    'noncash': [{'description': 'Equipment acquired via capital stock', 'amount': 2000.0}],
    'reconciliation': {'net_income': 800.0, 'depreciation': 0.0,
                       'working_capital': [{'name': '(Increase)/decrease in Accounts Receivable',
                                            'amount': -100.0}],
                       'total': 550.0},
    'net_change': 550.0, 'cash_begin': 0.0, 'cash_end': 550.0,
}


def test_direct_lines_cover_sections_note_and_reconciliation():
    labels = [ln['label'] for ln in cash_flow_lines(DIRECT_CF)]
    assert 'CASH FLOWS FROM OPERATING ACTIVITIES' in labels
    assert 'Cash received from customers' in labels
    assert 'CASH FLOWS FROM INVESTING ACTIVITIES' in labels
    assert 'CASH FLOWS FROM FINANCING ACTIVITIES' in labels
    assert 'NET INCREASE/(DECREASE) IN CASH' in labels
    assert 'Non-cash investing and financing transactions' in labels
    assert 'Equipment acquired via capital stock' in labels
    assert 'Reconciliation of net income to net cash from operating activities' in labels
    assert 'Net Income (period)' in labels


def test_direct_omits_noncash_block_when_empty():
    cf = {**DIRECT_CF, 'noncash': []}
    labels = [ln['label'] for ln in cash_flow_lines(cf)]
    assert 'Non-cash investing and financing transactions' not in labels
    # reconciliation note still present
    assert 'Reconciliation of net income to net cash from operating activities' in labels
