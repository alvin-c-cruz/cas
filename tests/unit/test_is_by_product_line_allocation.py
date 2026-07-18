from decimal import Decimal
import pytest
from app.reports.income_statement_by_product_line import (
    _allocation_shares, _distribute, UNALLOCATED)

pytestmark = [pytest.mark.unit]

D = lambda v: Decimal(str(v))


class TestAllocationShares:
    def test_none_basis_returns_empty(self):
        assert _allocation_shares('none', {}, {}, {}, [1, 2]) == {}

    def test_equal_split(self):
        shares = _allocation_shares('equal', {}, {}, {}, [1, 2])
        assert shares == {1: D('0.5'), 2: D('0.5')}

    def test_equal_split_no_categories_returns_empty(self):
        assert _allocation_shares('equal', {}, {}, {}, []) == {}

    def test_revenue_share(self):
        rev = {1: D(300), 2: D(100)}
        shares = _allocation_shares('revenue_share', rev, {}, {}, [1, 2])
        assert shares == {1: D('0.75'), 2: D('0.25')}

    def test_gross_profit_share(self):
        gp = {1: D(80), 2: D(20)}
        shares = _allocation_shares('gross_profit_share', {}, gp, {}, [1, 2])
        assert shares == {1: D('0.8'), 2: D('0.2')}

    def test_units_sold(self):
        units = {1: D(3), 2: D(1)}
        shares = _allocation_shares('units_sold', {}, {}, units, [1, 2])
        assert shares == {1: D('0.75'), 2: D('0.25')}

    def test_zero_total_basis_falls_to_unallocated(self):
        assert _allocation_shares('revenue_share', {1: D(0), 2: D(0)}, {}, {}, [1, 2]) == {}


class TestDistribute:
    def test_full_allocation_ties_exactly(self):
        out = _distribute(D(100), {1: D('0.75'), 2: D('0.25')})
        assert out[1] == D(75)
        assert out[2] == D(25)
        assert out[UNALLOCATED] == D(0)
        assert sum(out.values()) == D(100)

    def test_no_shares_goes_entirely_unallocated(self):
        out = _distribute(D(100), {})
        assert out == {UNALLOCATED: D(100)}

    def test_ties_exactly_for_any_shares(self):
        out = _distribute(D('33.33'), {1: D('1')})
        assert sum(out.values()) == D('33.33')
