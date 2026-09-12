"""The layout's chosen font must actually reach the browser on every pre-printed form.

Found on production 2026-09-12: APV and CDV layouts stored
`Calibri, Candara, "Segoe UI", sans-serif`, yet both printed in Times New Roman. The
templates emitted the value inside the inline `<style>` block, where Jinja's HTML
autoescape turns the quotes into `&#34;`. Browsers do NOT decode entities inside
`<style>` (raw-text element), so the declaration is invalid CSS and is dropped whole,
and the page falls to the UA default -- for every font in the picker whose stack quotes
a name (Courier New, Lucida Console, Trebuchet MS, Calibri ...). Only bare stacks like
Arial ever worked. The designer masked it: its live preview sets `body.style.fontFamily`
from the <select>, so the chosen face shows while editing and vanishes on reload.

The value is allow-listed by every module's sanitizer, but the fix here does not lean
on that: it goes in the `<body style="...">` ATTRIBUTE, where the HTML parser decodes
`&#34;` back to `"` before CSS ever sees it, so autoescape stays on.
"""
import html as html_lib
import re
from pathlib import Path

import pytest

from app.settings import AppSettings
from tests.integration.test_cdv_print_form import login, _cdv_with_je
from tests.integration.test_apv_print_form import _posted_apv

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements, pytest.mark.accounts_payable]

CALIBRI = 'Calibri, Candara, "Segoe UI", sans-serif'


def _body_font_family(html):
    """The font-family the browser will apply to <body>: read from its style ATTRIBUTE,
    entity-decoded the way the HTML parser does it. None when there is no such attr."""
    m = re.search(r'<body\b[^>]*\sstyle="([^"]*)"', html)
    if not m:
        return None
    style = html_lib.unescape(m.group(1))
    fm = re.search(r'font-family\s*:\s*([^;]+)', style)
    return fm.group(1).strip() if fm else None


def _style_blocks(html):
    return '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', html, flags=re.S))


class TestCdvPreprintedFont:

    def test_quoted_font_reaches_the_body_intact(self, client, db_session, admin_user, main_branch):
        from app.cash_disbursements.preprinted_layout import get_layout, save_layout
        cdv = _cdv_with_je(db_session, main_branch)
        lay = get_layout(main_branch.id)
        lay['page']['fontFamily'] = CALIBRI
        save_layout(lay, 'admin', main_branch.id)
        db_session.commit()
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        html = client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True)

        assert _body_font_family(html) == CALIBRI
        # and it is no longer emitted where the entity would poison the CSS
        assert '&#34;' not in _style_blocks(html)


class TestApvPreprintedFont:

    def test_quoted_font_reaches_the_body_intact(self, client, db_session, admin_user, main_branch):
        from app.accounts_payable.preprinted_layout import get_layout, save_layout
        ap = _posted_apv(db_session, main_branch)
        lay = get_layout(main_branch.id)
        lay['page']['fontFamily'] = CALIBRI
        save_layout(lay, 'admin', main_branch.id)
        db_session.commit()
        AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        html = client.get(f'/accounts-payable/{ap.id}/print').get_data(as_text=True)

        assert _body_font_family(html) == CALIBRI
        assert '&#34;' not in _style_blocks(html)


# Every pre-printed template shares the line. Rendering all twelve needs twelve document
# fixtures; the two above prove the behaviour, this pins the SOURCE of the rest so the
# next clone cannot quietly reintroduce the `<style>` emission.
_APP = Path(__file__).resolve().parents[2] / 'app'
_PREPRINTED_TEMPLATES = sorted(
    list(_APP.glob('*/templates/*/print_preprinted.html'))
    + list(_APP.glob('*/templates/*/payslip_print_preprinted.html'))
    + [_APP / 'cash_disbursements/templates/cash_disbursements/print_check.html'])


@pytest.mark.parametrize('tpl', _PREPRINTED_TEMPLATES, ids=lambda p: p.parent.name + '/' + p.name)
def test_template_puts_font_on_the_body_attribute_not_in_style(tpl):
    src = tpl.read_text(encoding='utf-8')
    style_src = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', src, flags=re.S))
    assert 'layout.page.fontFamily' not in style_src, tpl
    # Not `<body\b[^>]*>`: the templates mention a literal `<body>` in prose before the
    # real tag. Every real one carries data-can-edit.
    body_tag = re.search(r'<body\b[^>]*data-can-edit[^>]*>', src).group(0)
    assert re.search(r'style="[^"]*font-family:\s*\{\{\s*layout\.page\.fontFamily\s*\}\}', body_tag), body_tag


def test_guard_sees_all_twelve_templates():
    assert len(_PREPRINTED_TEMPLATES) == 12, [p.name for p in _PREPRINTED_TEMPLATES]
