"""Every row of a fixed-height print grid is the same height.

Owner report 2026-08-21, against /receiving-reports/1/print and then the PR:
"lines should have the same height. Currently the line with data's height is
too small. others have good height."

All three grids set the row height on the FILLER rows only --

    table.lines tbody tr.filler td { height: 19px; }

-- so a blank row was 19px while a row carrying data collapsed to whatever its
font and padding produced. The grid printed ragged, with the real lines visibly
shorter than the empty ones. The height belongs on every cell in the tbody.

The Sales Order grid had the same defect for one commit; its filler rule was
copied from this pattern the same day (761c8b31). Fixed here in the same pass
rather than waiting for it to be reported separately.

WHY THIS TEST READS THE TEMPLATE SOURCE: the rule is static CSS in each
template's own <style> block -- no Jinja, no request context, identical in
every render. Reading the file asserts exactly the same bytes the browser gets,
without standing up three different documents (an RR alone needs a vendor, a
PO and allocations). What it CANNOT see is the rendered millimetres; it asserts
the rule shape that produces them.
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.purchase_requests,
              pytest.mark.receiving_reports, pytest.mark.sales_orders]

APP = Path(__file__).resolve().parents[2] / 'app'

#: (label, template, the tbody-cell selector that must carry the height)
GRIDS = [
    ('receiving_report', 'receiving_reports/templates/receiving_reports/print.html',
     'table.lines tbody td'),
    ('purchase_request', 'purchase_requests/templates/purchase_requests/print.html',
     'table.lines tbody td'),
    ('sales_order', 'sales_orders/templates/sales_orders/print.html',
     'table.particulars tbody td'),
]

RULE = re.compile(r'([^{}]+)\{([^{}]*)\}')
COMMENT = re.compile(r'/\*.*?\*/', re.S)


def _rules(css):
    """[(selector, body), ...] -- flat, which is all these blocks contain.

    Comments are stripped FIRST. Everything between the previous `}` and the
    next `{` is the selector, so a comment sitting above a rule is swallowed
    into it -- and these rules are commented heavily enough that the word
    "filler" appears in the prose explaining why the height is NOT scoped to
    fillers. That alone made this test fail against correct CSS.
    """
    return [(m.group(1).strip(), m.group(2).strip())
            for m in RULE.finditer(COMMENT.sub('', css))]


def _height_rules(path):
    css = path.read_text(encoding='utf-8')
    return [(sel, body) for sel, body in _rules(css) if re.search(r'\bheight:\s*\d', body)]


@pytest.mark.parametrize('label,rel,selector', GRIDS, ids=[g[0] for g in GRIDS])
def test_row_height_applies_to_every_tbody_cell(label, rel, selector):
    path = APP / rel
    assert path.exists(), path

    matching = [(sel, body) for sel, body in _height_rules(path)
                if sel == selector]
    assert matching, (
        f'{label}: no height rule on "{selector}" -- data rows will collapse to '
        f'their content while filler rows keep theirs')


@pytest.mark.parametrize('label,rel,selector', GRIDS, ids=[g[0] for g in GRIDS])
def test_no_height_rule_targets_filler_rows_alone(label, rel, selector):
    """The defect itself, pinned.

    A height scoped to `.filler` / `.so-filler` and nothing else is exactly what
    made the grid ragged. If a future change needs filler rows sized differently
    it should say so deliberately -- and this test is where that argument gets
    had.
    """
    path = APP / rel
    offenders = [sel for sel, _ in _height_rules(path) if 'filler' in sel]
    assert not offenders, (
        f'{label}: height is scoped to filler rows only -> {offenders}')


@pytest.mark.parametrize('label,rel,selector', GRIDS, ids=[g[0] for g in GRIDS])
def test_the_grid_still_has_filler_rows(label, rel, selector):
    """CONTROL: the fix must not be "delete the filler rows".

    Without this, removing padding entirely would satisfy both tests above while
    destroying the fixed-height grid the owner asked for.
    """
    css = (APP / rel).read_text(encoding='utf-8')
    assert re.search(r'class="(so-)?filler"', css), \
        f'{label}: the grid no longer emits filler rows'
