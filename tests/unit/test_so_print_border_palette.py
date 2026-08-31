"""The SO printout draws every 1px border in one colour.

Owner directive 2026-08-31: "borders should have consistent color. the final
printout has Black and Grey."

Measured before changing anything -- the sheet carried FIVE border colours, and
the jarring pair sat inside a single table: `.particulars th` was #555 while
`.particulars td` was #aaa, so the line grid's header row was outlined darker
than its own body.

    .particulars th      #555        <- the outlier
    .particulars td      #aaa
    .info-row td         #aaa
    .notes-box           #aaa
    .sig-box             #aaa
    .sig-box .sig-line   #666
    .audit-footer        #ddd
    .so-header           #111, 2px

Every 1px border is now #aaa. TWO deliberate exceptions remain, and they are
asserted as exceptions rather than quietly allowed:

* `.so-header` is a 2px rule under the document title -- a different weight
  doing a different job (emphasis), not a box outline;
* `.print-rev-banner` is 2px #c00, where the colour IS the meaning (a superseded
  revision) and flattening it to grey would destroy the signal.

WHY THIS READS THE TEMPLATE SOURCE: the rules are static CSS in the template's
own <style> block, identical in every render (same rationale as
test_so_print_font_scale.py). Screen chrome (.btn-print/.btn-close) declares
`border: none` and never reaches paper.
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]

TEMPLATE = (Path(__file__).resolve().parents[2]
            / 'app/sales_orders/templates/sales_orders/print.html')

BORDER_COLOUR = '#aaa'
COMMENT = re.compile(r'/\*.*?\*/', re.S)

#: 2px rules whose colour is deliberate -- weight or meaning, not a box outline
ALLOWED_THICK = {('2px', '#111'), ('2px', '#c00')}

DECL = re.compile(r'border(?:-(?:top|right|bottom|left))?\s*:\s*'
                  r'(\d+px)\s+solid\s+(#[0-9a-fA-F]{3,6})')


def _declarations():
    css = COMMENT.sub('', TEMPLATE.read_text(encoding='utf-8'))
    style = re.search(r'<style>(.*?)</style>', css, re.S)
    assert style, 'no <style> block in the printout template'
    return DECL.findall(style.group(1))


def test_the_template_actually_declares_borders():
    """Guard against the whole file being parsed as empty -- every assertion
    below would pass vacuously against zero declarations."""
    assert len(_declarations()) >= 8


def test_every_one_pixel_border_is_the_same_colour():
    offenders = sorted({c.lower() for w, c in _declarations()
                        if w == '1px' and c.lower() != BORDER_COLOUR})
    assert not offenders, f'1px borders in other colours: {offenders}'


def test_the_only_other_borders_are_the_deliberate_thick_rules():
    thick = {(w, c.lower()) for w, c in _declarations() if w != '1px'}
    assert thick <= ALLOWED_THICK, f'unexpected non-1px border rules: {sorted(thick - ALLOWED_THICK)}'


def test_the_line_grid_header_matches_its_own_body():
    """THE reported symptom, pinned on its own: header and body cells of the
    particulars table must not disagree, which is what read as black-and-grey."""
    css = COMMENT.sub('', TEMPLATE.read_text(encoding='utf-8'))
    th = re.search(r'\.particulars th \{[^}]*\}', css)
    td = re.search(r'\.particulars td \{[^}]*\}', css)
    assert th and td, 'particulars th/td rules not found'
    th_c = DECL.search(th.group(0))
    td_c = DECL.search(td.group(0))
    assert th_c and td_c, 'particulars th/td declare no solid border'
    assert th_c.group(2).lower() == td_c.group(2).lower() == BORDER_COLOUR
