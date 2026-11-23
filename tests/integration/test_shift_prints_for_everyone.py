"""SHIFT-SCALE: the page shift prints for everyone who prints, and the print clips at the paper's edge.

Work order 2026-11-23-page-shift-shrinks-print.md, including its second bug (found 23 Nov ~13:30): the shift's print rule
was written by templates/_pp_paper_extra.html, which all 12 pages include inside `{% if can_edit_layout %}`. So a user who
may not edit the layout printed WITHOUT the shift: a viewer on the 11 pre-printed prints, and on the cheque (editable by
admin and Chief Accountant only) a staff or accountant user.

Now the rule comes from templates/_pp_print_shift.html, included by every page outside that block, right after its
@page rule. It clips the canvas at the paper's edge and moves the placed fields (the CSS `translate` property on .pp-el,
.pp-col, .pp-jecol) instead of the canvas. The browser side (no shrink; fields move by the shift; a printed PDF) is
tests/e2e/test_shift_clips_at_paper_edge.py.
"""
import re
from pathlib import Path

import pytest

from app.settings import AppSettings
from tests.integration.test_cd_check_print import _check_cdv
from tests.integration.test_cdv_print_form import _cdv_with_je, login

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]

RULE = ('@media print { #ppCanvas { overflow: hidden; } '
        '#ppCanvas .pp-el, #ppCanvas .pp-col, #ppCanvas .pp-jecol { translate: 1.2mm -0.8mm; } }')
RULE_AT_ZERO = ('@media print { #ppCanvas { overflow: hidden; } '
                '#ppCanvas .pp-el, #ppCanvas .pp-col, #ppCanvas .pp-jecol { translate: 0.0mm 0.0mm; } }')

_APP = Path(__file__).resolve().parents[2] / 'app'
_PAGES = sorted(
    list(_APP.glob('*/templates/*/print_preprinted.html'))
    + list(_APP.glob('*/templates/*/payslip_print_preprinted.html'))
    + [_APP / 'cash_disbursements/templates/cash_disbursements/print_check.html'])


def _rule(html):
    m = re.search(r'<style id="ppShiftStyle">(.*?)</style>', html, re.S)
    return m.group(1) if m else None


def _as(client, username, password, branch):
    login(client, username=username, password=password)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


class TestEveryonePrintsWithTheShift:

    def test_a_viewer_on_the_preprinted_voucher(self, client, db_session, viewer_user, admin_user, main_branch):
        from app.cash_disbursements.preprinted_layout import get_layout, save_layout
        viewer_user.set_branches([main_branch]); db_session.commit()
        cdv = _cdv_with_je(db_session, main_branch)
        lay = get_layout(main_branch.id)
        lay['offset'] = {'x': 1.2, 'y': -0.8}
        save_layout(lay, 'admin', main_branch.id)
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        db_session.commit()
        _as(client, 'viewer', 'viewer123', main_branch)
        html = client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True)
        assert 'id="editLayoutBtn"' not in html, 'a viewer was given the designer'
        assert _rule(html) == RULE

    def test_a_staff_user_on_the_cheque(self, client, db_session, staff_user, admin_user, main_branch):
        from app.cash_disbursements.check_layout import get_layout, save_layout
        staff_user.set_branches([main_branch]); db_session.commit()
        cdv = _check_cdv(db_session, main_branch)
        lay = get_layout(cdv.cash_account_id)
        lay['offset'] = {'x': 1.2, 'y': -0.8}
        save_layout(lay, 'admin', cdv.cash_account_id)
        db_session.commit()
        _as(client, 'staff', 'staff123', main_branch)
        resp = client.get(f'/cash-disbursements/{cdv.id}/print-check')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="editLayoutBtn"' not in html, 'staff was given the cheque designer'
        assert _rule(html) == RULE

    def test_no_shift_still_clips_at_the_edge(self, client, db_session, viewer_user, admin_user, main_branch):
        viewer_user.set_branches([main_branch]); db_session.commit()
        cdv = _cdv_with_je(db_session, main_branch)
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        db_session.commit()
        _as(client, 'viewer', 'viewer123', main_branch)
        assert _rule(client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True)) == RULE_AT_ZERO


def _open_blocks_at(src, needle):
    """The {% if %} / {% for %} blocks still open where `needle` first appears."""
    stack = []
    for m in re.finditer(r'{%-?\s*(if|endif|for|endfor)\b([^%]*)%}', src[:src.index(needle)]):
        if m.group(1) in ('if', 'for'):
            stack.append(m.group(2).strip())
        else:
            stack.pop()
    return stack


@pytest.mark.parametrize('tpl', _PAGES, ids=lambda p: p.parent.name + '/' + p.name)
def test_every_page_writes_the_rule_for_every_user(tpl):
    src = tpl.read_text(encoding='utf-8')
    include = "{% include '_pp_print_shift.html' %}"
    assert src.count(include) == 1, tpl
    assert _open_blocks_at(src, include) == [], f'{tpl.name}: the shift rule sits inside a block'
    # on the line right after the page's @page rule
    page_rule = re.search(r'<style id="ppPageStyle">[^\n]*</style>\r?\n', src)
    assert page_rule and src[page_rule.end():].startswith(include), tpl


def test_all_twelve_pages_are_checked():
    assert len(_PAGES) == 12


def test_the_designer_controls_no_longer_carry_the_rule():
    assert 'ppShiftStyle' not in (_APP / 'templates/_pp_paper_extra.html').read_text(encoding='utf-8')


def test_the_designer_rewrites_the_same_rule():
    js = (_APP / 'static/js/pp_paper.js').read_text(encoding='utf-8')
    assert ("'@media print { #ppCanvas { overflow: hidden; } #ppCanvas .pp-el, #ppCanvas .pp-col, #ppCanvas .pp-jecol "
            "{ translate: ' + s.x + 'mm ' + s.y + 'mm; } }'") in js
