"""Unit tests for module_key_for_endpoint's prefix-matching safety.

See docs/superpowers/plans/2026-07-19-... (R-03a slice 2 retro) and
project-bug-tracker BUG-MODULEKEY-PREFIX-COLLISION-ORDERING: a bare endpoint
prefix like 'reports.income_statement' can textually match a DIFFERENT,
longer, unrelated endpoint name like
'reports.income_statement_by_product_line' via plain `.startswith()`,
silently resolving to the wrong module regardless of intent -- whichever
entry happens to sit first in MODULE_REGISTRY wins, which is an ordering
accident, not a deliberate design.

The fix (longest-matching-prefix-wins) must NOT break the OTHER, legitimate
use of bare (non-dot-terminated) prefixes in this registry: several modules
deliberately split one Flask blueprint into multiple gated sub-modules by a
shared endpoint-name STEM rather than a full dot-boundary -- e.g.
'sales_memos.credit_' covers credit_list/credit_create/credit_view/... as the
`credit_memos` module, while 'sales_memos.debit_' covers the sibling
`debit_memos` module in the SAME blueprint. These tests use a synthetic
registry (deliberately ordered with the short/core entry FIRST, the worst
case) to prove both properties hold regardless of registry order.
"""
from unittest.mock import patch
import pytest
from app.users import module_access

pytestmark = [pytest.mark.unit]

_SYNTHETIC_REGISTRY = [
    {'key': 'income_statement', 'optional': False,
     'endpoints': ('reports.income_statement', 'reports.income_statement_print')},
    {'key': 'income_statement_by_product_line', 'optional': True,
     'endpoints': ('reports.income_statement_by_product_line',
                   'reports.income_statement_by_product_line_print')},
    {'key': 'product_categories', 'optional': True,
     'endpoints': ('product_categories.',)},
    {'key': 'credit_memos', 'optional': True,
     'endpoints': ('sales_memos.credit_',)},
    {'key': 'debit_memos', 'optional': True,
     'endpoints': ('sales_memos.debit_',)},
]


class TestModuleKeyForEndpointPrefixSafety:
    def test_bare_prefix_does_not_swallow_a_longer_sibling_endpoint(self):
        with patch.object(module_access, 'MODULE_REGISTRY', _SYNTHETIC_REGISTRY):
            assert module_access.module_key_for_endpoint(
                'reports.income_statement_by_product_line') == 'income_statement_by_product_line'

    def test_bare_prefix_still_matches_its_own_exact_endpoint(self):
        with patch.object(module_access, 'MODULE_REGISTRY', _SYNTHETIC_REGISTRY):
            assert module_access.module_key_for_endpoint('reports.income_statement') == 'income_statement'

    def test_bare_prefix_still_matches_its_own_listed_sibling(self):
        with patch.object(module_access, 'MODULE_REGISTRY', _SYNTHETIC_REGISTRY):
            assert module_access.module_key_for_endpoint('reports.income_statement_print') == 'income_statement'

    def test_trailing_dot_blueprint_prefix_still_matches_any_view_in_that_blueprint(self):
        with patch.object(module_access, 'MODULE_REGISTRY', _SYNTHETIC_REGISTRY):
            assert module_access.module_key_for_endpoint('product_categories.list') == 'product_categories'
            assert module_access.module_key_for_endpoint('product_categories.create') == 'product_categories'

    def test_stem_prefix_still_matches_every_sub_action_in_its_blueprint(self):
        """The legitimate 'split one blueprint into two modules by name stem' pattern
        (credit_memos / debit_memos both live in sales_memos) must keep working --
        the fix must not require these to become dot-terminated or be enumerated."""
        with patch.object(module_access, 'MODULE_REGISTRY', _SYNTHETIC_REGISTRY):
            assert module_access.module_key_for_endpoint('sales_memos.credit_list') == 'credit_memos'
            assert module_access.module_key_for_endpoint('sales_memos.credit_create') == 'credit_memos'
            assert module_access.module_key_for_endpoint('sales_memos.credit_void') == 'credit_memos'
            assert module_access.module_key_for_endpoint('sales_memos.debit_list') == 'debit_memos'
            assert module_access.module_key_for_endpoint('sales_memos.debit_create') == 'debit_memos'

    def test_unrelated_endpoint_returns_none(self):
        with patch.object(module_access, 'MODULE_REGISTRY', _SYNTHETIC_REGISTRY):
            assert module_access.module_key_for_endpoint('reports.balance_sheet') is None
