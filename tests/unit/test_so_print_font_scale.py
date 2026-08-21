"""The SO printout's type scale.

Owner directive 2026-08-21: "1.2x font size", following a readout of the
header and detail sizes. Every printed size was multiplied by 1.2 and written
literally (12px, 10.8px, 19.2px ...) rather than rounded, because the directive
was a multiplier.

The Print/Close buttons are deliberately EXCLUDED: they are screen chrome that
never reaches the paper, and growing them would change the on-screen UI for no
printed benefit.

The whole scale is pinned in one table. It reads as a lot of assertions, but a
type scale is exactly the thing that drifts one selector at a time -- a later
"just bump the total" leaves the ladder inconsistent, and this is where that
gets caught.

WHY THIS READS THE TEMPLATE SOURCE: the rules are static CSS in the template's
own <style> block, identical in every render. It asserts the declared sizes,
not the rendered millimetres.
"""
import io
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]

TEMPLATE = (Path(__file__).resolve().parents[2]
            / 'app/sales_orders/templates/sales_orders/print.html')

#: selector -> declared font-size, after the 1.2x scale
EXPECTED = {
    'body': '13.2px',
    '.so-header .company-name': '19.2px',
    '.so-header .company-sub': '12px',
    '.so-header .doc-title': '16.8px',
    '.info-row table': '12px',
    '.particulars': '12px',
    '.section-label': '12px',
    '.summary-inner': '12px',
    '.summary-net .netlabel': '13.2px',
    '.summary-net .netval': '15.6px',
    '.notes-box': '12px',
    '.notes-box .notes-label': '10.8px',
    '.sig-box .sig-title': '10.8px',
    '.sig-box .sig-line': '10.8px',
    '.sig-box .sig-line--named': '12px',
    '.audit-footer': '10.8px',
    '.print-rev-banner .print-rev': '16.8px',
    '.print-rev-banner .print-rev-supersede': '12px',
    # screen chrome -- NOT scaled
    '.btn-print': '13px',
    '.btn-close': '13px',
}

COMMENT = re.compile(r'/\*.*?\*/', re.S)


def _declared_sizes():
    css = io.open(TEMPLATE, encoding='utf-8').read()
    css = css[css.index('<style>'):css.index('</style>')]
    css = COMMENT.sub('', css)
    out = {}
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
        fs = re.search(r'font-size:\s*([^;]+);', m.group(2))
        if fs:
            out[' '.join(m.group(1).split())] = fs.group(1).strip()
    return out


def test_every_printed_size_is_the_scaled_value():
    actual = _declared_sizes()
    assert actual == EXPECTED


@pytest.mark.parametrize('selector', ['.btn-print', '.btn-close'])
def test_screen_chrome_was_not_scaled(selector):
    """CONTROL: the scale applies to the DOCUMENT, not the page furniture.

    Without this, a blanket regex over every font-size in the file would pass
    the table above while also inflating the buttons.
    """
    assert _declared_sizes()[selector] == '13px'


def test_the_grid_row_height_still_clears_the_larger_text():
    """The 25.5px row floor must still exceed the cell's own content height.

    12px text plus 3px padding top and bottom is ~21.6px; if the text ever grows
    past the floor the 20-row grid silently gets taller and the single-page
    layout stops holding. This is the assertion that catches that.
    """
    css = io.open(TEMPLATE, encoding='utf-8').read()
    assert 'table.particulars tbody td { height: 25.5px; }' in css
    assert _declared_sizes()['.particulars'] == '12px'
    assert re.search(r'\.particulars td \{[^}]*padding:\s*3px', css), \
        'cell padding changed -- recheck that content still fits the 25.5px floor'
