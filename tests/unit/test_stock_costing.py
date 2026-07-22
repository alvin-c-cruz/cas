from decimal import Decimal
from app.stock_adjustments.costing import compute_new_balance

D = Decimal

def test_moving_average_recompute_on_receipt():
    # 10 @ 5.00, receive 10 @ 7.00 -> 20 @ 6.00
    qty, avg = compute_new_balance('moving_average', D('10'), D('5.00'), D('10'), D('7.00'), None)
    assert qty == D('20.0000')
    assert avg == D('6.00')

def test_moving_average_issue_keeps_avg():
    # 20 @ 6.00, issue 5 -> 15 @ 6.00 (avg unchanged; in_unit_cost irrelevant)
    qty, avg = compute_new_balance('moving_average', D('20'), D('6.00'), D('-5'), None, None)
    assert qty == D('15.0000')
    assert avg == D('6.00')

def test_moving_average_from_zero_uses_receipt_cost():
    qty, avg = compute_new_balance('moving_average', D('0'), D('0.00'), D('8'), D('4.25'), None)
    assert qty == D('8.0000')
    assert avg == D('4.25')

def test_standard_always_tracks_standard_cost_on_receipt():
    # standard product: avg stays standard_cost even though in_unit_cost differs
    qty, avg = compute_new_balance('standard', D('10'), D('3.00'), D('10'), D('99.99'), D('3.00'))
    assert qty == D('20.0000')
    assert avg == D('3.00')

def test_standard_issue():
    qty, avg = compute_new_balance('standard', D('20'), D('3.00'), D('-4'), None, D('3.00'))
    assert qty == D('16.0000')
    assert avg == D('3.00')

def test_lifo_specific_identification_fall_back_to_moving_average():
    # fifo is intentionally excluded here (R-03 2b) -- post_movement no longer
    # calls compute_new_balance for a fifo-costed product at all (see fifo.py);
    # this pure function's own fifo behavior is untouched but no longer
    # production-reachable, so asserting it here would be misleading.
    for method in ('lifo', 'specific_identification'):
        qty, avg = compute_new_balance(method, D('10'), D('5.00'), D('10'), D('7.00'), None)
        assert avg == D('6.00'), method
