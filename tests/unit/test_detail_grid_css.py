"""Guard: the shared .detail-grid used by DR/PO/PR/RR detail pages must be
defined in style.css (it was applied by four templates but defined nowhere),
and the DR detail page must use the <div><strong> idiom its siblings use so
one rule styles all four consistently. BUG-DR-DETAIL-GRID-UNSTYLED."""
import re
from pathlib import Path
import pytest

pytestmark = [pytest.mark.unit]


def test_detail_grid_rule_defined_in_stylesheet():
    css = Path('app/static/css/style.css').read_text(encoding='utf-8')
    assert re.search(r'\.detail-grid\s*\{', css), \
        '.detail-grid must be defined in style.css (was undefined -> unstyled)'


def test_detail_grid_has_responsive_collapse():
    css = Path('app/static/css/style.css').read_text(encoding='utf-8')
    assert re.search(r'@media[^{]*max-width:\s*768px[^{]*\{[^}]*\.detail-grid', css, re.S), \
        '.detail-grid must collapse to one column at <=768px'


def test_dr_detail_uses_div_grid_not_dl():
    tpl = Path('app/delivery_receipts/templates/delivery_receipts/detail.html').read_text(encoding='utf-8')
    assert '<dl class="detail-grid">' not in tpl, 'DR detail must not use the <dl> markup'
    assert '<div class="detail-grid">' in tpl, 'DR detail must use the <div class="detail-grid"> idiom'
