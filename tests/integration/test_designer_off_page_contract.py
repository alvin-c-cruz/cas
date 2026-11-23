"""RICL-W A: the off-page check (static/js/pp_paper.js) skips what does not print by its CSS classes.

The browser tests (tests/e2e/test_designer_warns_fields_off_page.py) drive three designer families on real pages. The
other pages are held to the same contract here: every class that hides a field, column, band or journal face on any of
the twelve print pages (or in a designer stylesheet) is one the check knows, so a hidden field is never listed as off the
page. A page that adds a new hiding class fails this test until the check learns it.
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

_APP = Path(__file__).resolve().parents[2] / 'app'
_PAGES = sorted(
    list(_APP.glob('*/templates/*/print_preprinted.html'))
    + list(_APP.glob('*/templates/*/payslip_print_preprinted.html'))
    + [_APP / 'cash_disbursements/templates/cash_disbursements/print_check.html'])
_STYLESHEETS = sorted((_APP / 'static/css').glob('*designer*.css'))

#: What the check skips (pp_paper.js HIDDEN).
SKIPPED = {'pp-field-hidden', 'pp-col-hidden', 'pp-band-off', 'pp-je-inactive'}
#: Hidden things that are never a field: the cheque's on-screen background picture, the boxed date's drag grip
#: (inside its field, so counted with it).
NOT_FIELDS = {'pp-bg', 'pp-boxed-grip'}

_HIDING_RULE = re.compile(r'^\s*\.(pp-[a-z-]+)\s*\{\s*display:\s*none', re.M)


def _js():
    return (_APP / 'static/js/pp_paper.js').read_text(encoding='utf-8')


def test_the_check_skips_exactly_the_known_hiding_classes():
    m = re.search(r"const HIDDEN = '([^']*)';", _js())
    assert m, 'pp_paper.js has no HIDDEN list'
    assert {c.strip().lstrip('.') for c in m.group(1).split(',')} == SKIPPED


def test_all_twelve_pages_are_checked():
    assert len(_PAGES) == 12


@pytest.mark.parametrize('src', _PAGES + _STYLESHEETS, ids=lambda p: p.parent.name + '/' + p.name)
def test_every_hiding_class_is_one_the_check_knows(src):
    found = set(_HIDING_RULE.findall(src.read_text(encoding='utf-8')))
    assert found <= SKIPPED | NOT_FIELDS, f'{src.name} hides with {sorted(found - SKIPPED - NOT_FIELDS)}'


def test_the_mark_and_the_bar_stay_off_paper():
    partial = (_APP / 'templates/_pp_paper_extra.html').read_text(encoding='utf-8')
    assert re.search(r'@media screen \{ #ppCanvas \[data-pp-off\] \{ outline: 2px solid #c62828', partial)
    assert '@media print { .pp-off-page { display: none !important; } }' in partial
    assert "js/pp_paper.js') }}?v=2" in partial, 'bump the cache-buster with the script'
