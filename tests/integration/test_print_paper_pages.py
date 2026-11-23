"""RICL-1 A + RICL-2 A on the print pages: a custom paper reaches the canvas, the @page rule and the paper picker,
and the whole-page shift reaches the print CSS (paper only) and the designer's inputs.

Owner, 17 Nov 2026: "Custom size" on every pre-printed layout and the cheque (RICL-1 A); a "Shift whole page" in mm
on each (RICL-2 A). Rendering all twelve pages needs twelve document fixtures: the CDV, APV and cheque pages prove
the behaviour, and a source check pins the other templates to the same two lines.
"""
import json
import re
from pathlib import Path

import pytest

from app.settings import AppSettings
from tests.integration.test_cdv_print_form import login, _cdv_with_je
from tests.integration.test_apv_print_form import _posted_apv
from tests.integration.test_cd_check_print import _check_cdv

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements, pytest.mark.accounts_payable]

CUSTOM = {'paper': 'custom', 'paperSize': {'w': 9.5, 'h': 6.5}, 'offset': {'x': 1.2, 'y': -0.8}}


def _open(client, branch):
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _assert_custom_page(html):
    # canvas sized from the custom paper: 9.5in x 6.5in at 96 px/in
    canvas = re.search(r'<div[^>]*id="ppCanvas"[^>]*>', html).group(0)
    assert 'width:912px' in canvas.replace(' ', '') and 'height:624px' in canvas.replace(' ', ''), canvas
    # the browser's page size
    page_style = re.search(r'<style id="ppPageStyle">(.*?)</style>', html, flags=re.S).group(1)
    assert 'size: 9.5in 6.5in' in page_style, page_style
    # the paper picker offers and selects "Custom size", carrying its geometry for the designer
    opt = re.search(r'<option value="custom"[^>]*>[^<]*</option>', html).group(0)
    assert 'selected' in opt and 'data-css="9.5in 6.5in"' in opt and 'Custom size' in opt, opt
    # the shift: on paper only, in mm; it moves the fields inside a canvas that clips at the paper (SHIFT-SCALE)
    shift = re.search(r'<style id="ppShiftStyle">(.*?)</style>', html, flags=re.S).group(1)
    assert '@media print' in shift and 'translate: 1.2mm -0.8mm;' in shift and 'overflow: hidden' in shift, shift
    # the designer's inputs carry the saved values
    assert re.search(r'id="ppPaperW"[^>]*value="9.5"', html)
    assert re.search(r'id="ppPaperH"[^>]*value="6.5"', html)
    assert re.search(r'id="ppShiftX"[^>]*value="1.2"', html)
    assert re.search(r'id="ppShiftY"[^>]*value="-0.8"', html)
    assert 'js/pp_paper.js' in html


def _assert_plain_page(html):
    # an old layout: continuous paper, no shift, the custom option offered but not selected
    page_style = re.search(r'<style id="ppPageStyle">(.*?)</style>', html, flags=re.S).group(1)
    assert 'size: 9.5in 10.5in' in page_style, page_style
    opt = re.search(r'<option value="custom"[^>]*>', html).group(0)
    assert 'selected' not in opt
    assert 'translate: 0.0mm 0.0mm;' in re.search(r'<style id="ppShiftStyle">(.*?)</style>', html, flags=re.S).group(1)


class TestCdvPage:

    def test_custom_paper_and_shift_render(self, client, db_session, admin_user, main_branch):
        from app.cash_disbursements.preprinted_layout import get_layout, save_layout
        cdv = _cdv_with_je(db_session, main_branch)
        lay = get_layout(main_branch.id)
        lay.update(CUSTOM)
        save_layout(lay, 'admin', main_branch.id)
        db_session.commit()
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        _open(client, main_branch)
        resp = client.get(f'/cash-disbursements/{cdv.id}/print')
        assert resp.status_code == 200
        _assert_custom_page(resp.get_data(as_text=True))

    def test_an_old_layout_renders_unchanged(self, client, db_session, admin_user, main_branch):
        cdv = _cdv_with_je(db_session, main_branch)
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        _open(client, main_branch)
        _assert_plain_page(client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True))

    def test_save_route_keeps_custom_paper_and_shift(self, client, db_session, admin_user, main_branch):
        from app.cash_disbursements.preprinted_layout import LAYOUT_SETTING_KEY
        _open(client, main_branch)
        resp = client.post('/cash-disbursements/print-layout',
                           json={'paper': 'custom', 'paperSize': {'w': 7, 'h': 8.5}, 'offset': {'x': 99, 'y': 'x'}})
        assert resp.status_code == 200
        lay = resp.get_json()['layout']
        assert lay['paper'] == 'custom' and lay['paperSize'] == {'w': 7.0, 'h': 8.5}
        assert lay['offset'] == {'x': 20.0, 'y': 0.0}     # clamped / junk dropped
        stored = json.loads(AppSettings.get_setting(f'{LAYOUT_SETTING_KEY}:{main_branch.id}'))
        assert stored['paperSize'] == {'w': 7.0, 'h': 8.5}


class TestApvPage:

    def test_custom_paper_and_shift_render(self, client, db_session, admin_user, main_branch):
        from app.accounts_payable.preprinted_layout import get_layout, save_layout
        ap = _posted_apv(db_session, main_branch)
        lay = get_layout(main_branch.id)
        lay.update(CUSTOM)
        save_layout(lay, 'admin', main_branch.id)
        db_session.commit()
        AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
        _open(client, main_branch)
        resp = client.get(f'/accounts-payable/{ap.id}/print')
        assert resp.status_code == 200
        _assert_custom_page(resp.get_data(as_text=True))


class TestChequePage:

    def test_custom_paper_and_shift_render(self, client, db_session, admin_user, main_branch):
        from app.cash_disbursements.check_layout import get_layout, save_layout
        cdv = _check_cdv(db_session, main_branch)
        lay = get_layout(cdv.cash_account_id)
        lay.update(CUSTOM)
        save_layout(lay, 'admin', cdv.cash_account_id)
        db_session.commit()
        _open(client, main_branch)
        resp = client.get(f'/cash-disbursements/{cdv.id}/print-check')
        assert resp.status_code == 200
        _assert_custom_page(resp.get_data(as_text=True))


_APP = Path(__file__).resolve().parents[2] / 'app'
_TEMPLATES = sorted(
    list(_APP.glob('*/templates/*/print_preprinted.html'))
    + list(_APP.glob('*/templates/*/payslip_print_preprinted.html'))
    + [_APP / 'cash_disbursements/templates/cash_disbursements/print_check.html'])


@pytest.mark.parametrize('tpl', _TEMPLATES, ids=lambda p: p.parent.name + '/' + p.name)
def test_every_print_page_carries_the_custom_paper_and_shift(tpl):
    src = tpl.read_text(encoding='utf-8')
    # the paper list is widened with this layout's custom size before anything reads it
    first = src.index('pp_paper_ctx(layout, paper_sizes, paper_labels)')
    assert first < src.index('paper_sizes[') and first < src.index('paper_sizes.items()'), tpl
    # the controls sit right after the paper picker
    sel_end = src.index('</select>', src.index('id="ppPaper"'))
    assert src.index("{% include '_pp_paper_extra.html' %}") > sel_end, tpl


def test_all_twelve_pages_are_checked():
    assert len(_TEMPLATES) == 12


@pytest.mark.parametrize('js', sorted((_APP / 'static/js').glob('*designer*.js')), ids=lambda p: p.name)
def test_every_designer_saves_the_size_and_shift(js):
    src = js.read_text(encoding='utf-8')
    # collect() spreads the shared controls' values beside `paper`
    assert re.search(r"paper: \(paperSel && paperSel\.value\)[^\n]*\n\s*\.\.\.\(window\.ppPaperExtra \? window\.ppPaperExtra\(\) : \{\}\),",
                     src), js.name
