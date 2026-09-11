"""The stock-adjustment product picker shows the NAME, never 'null - Widget'.

Owner, 2026-09-10. Retiring the product code (making it optional) turned this
picker into a live defect in a module the retirement plan deliberately did NOT
touch: the label was built as `p.code + ' - ' + p.name` UNCONDITIONALLY, so
every product created since the code became optional renders as

    null - Widget

`p.code` arrives as JSON null, and JavaScript stringifies it into the label.
Two of the three sibling pickers (delivery receipts, sales memos) guard with a
ternary and degrade to the name; this one did not.

The ordering carried the same fault: ORDER BY Product.code puts SQLite's NULLs
FIRST, so every new product clumped at the top of the list in arbitrary order --
ahead of the 566 coded products the user is actually looking for.

This is Phase 2 territory by scope, taken early because it is user-visible now.
The payload keeps its `code` key: Product.to_dict() and several sales-side
pickers still read it, and removing it needs the full consumer sweep Phase 2
carries.
"""
import pathlib
import re

import pytest

pytestmark = [pytest.mark.integration]

JS = pathlib.Path('app/static/js/stock_adjustments_form.js')
VIEWS = pathlib.Path('app/stock_adjustments/views.py')


class TestTheLabel:

    def test_it_does_not_concatenate_the_code(self):
        src = JS.read_text(encoding='utf-8')
        assert "p.code + ' - ' + p.name" not in src

    def test_it_shows_the_name(self):
        src = JS.read_text(encoding='utf-8')
        m = re.search(r'opt\.textContent = ([^;]+);', src)
        assert m, 'the option label is not built where expected'
        assert 'p.name' in m.group(1), m.group(1)

    def test_no_unguarded_code_read_is_left_in_the_file(self):
        """Scoped to a real read of the product's own code, not the word
        'code' -- which appears in prose and in costing_method handling."""
        src = JS.read_text(encoding='utf-8')
        assert not re.search(r'\bp\.code\b(?!\s*\?)', src), (
            'an unguarded p.code read remains; it renders the string "null"')


class TestTheOrdering:

    def test_products_are_not_ordered_by_the_retired_code(self):
        """SQLite sorts NULLs FIRST, so ordering on a now-usually-empty column
        buries the coded products beneath every new one."""
        src = VIEWS.read_text(encoding='utf-8')
        assert 'order_by(Product.code)' not in src

    def test_they_are_ordered_by_name(self):
        src = VIEWS.read_text(encoding='utf-8')
        assert 'order_by(Product.name)' in src


class TestThePayloadIsUntouched:

    def test_the_code_key_still_ships(self):
        """CONTROL, and a deliberate scope line: the key stays because
        Product.to_dict() and the sales-side pickers still read it. Dropping it
        here would be a Phase 2 change made without Phase 2's consumer sweep --
        exactly how the purchase-order picker once shipped 'undefined'.
        """
        src = VIEWS.read_text(encoding='utf-8')
        assert "'code': p.code" in src
