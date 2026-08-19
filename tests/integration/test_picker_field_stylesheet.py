"""A header Choices picker must reach the stylesheet that gives it a border.

The defect this pins: transactions.css styles EVERY `.choices__inner` as a flat
in-grid control (transparent border and background, `!important`), which is right
inside a line-item cell and wrong for a picker sitting in a form row beside
ordinary .form-control inputs. `.picker-field` opts a header picker back out --
but that rule lived in accounts_payable_form.css, which the Receiving Report form
does not load, so its Vendor field rendered as bare borderless text while the
Purchase Order form (which does load it) looked correct.

These are render/link assertions on purpose. The bug was invisible to every
existing test because nothing was wrong with the MARKUP -- the `.picker-field`
class was present and correct on both forms. What differed was which stylesheet
the page pulled in, which only a rendered <link> can show.
"""
import re

import pytest

pytestmark = [pytest.mark.integration]

CSS = 'app/static/transactions.css'

# Every form that renders a header picker inside `.picker-field`, enumerated from
# the templates rather than assumed -- the Purchase Requisition was in this list
# first and does NOT belong: its header carries no picker at all (its Choices
# controls are line-item product/UOM cells, which SHOULD stay flat).
PICKER_FORMS = (
    'app/receiving_reports/templates/receiving_reports/form.html',
    'app/purchase_orders/templates/purchase_orders/form.html',
)


def _read(root, rel):
    return (root / rel).read_text(encoding='utf-8')


@pytest.fixture
def repo_root():
    from pathlib import Path
    return Path(__file__).resolve().parents[2]


def test_the_picker_field_rule_lives_in_transactions_css(repo_root):
    """It must sit in the file every picker-bearing form loads, beside the rules
    it overrides -- not in a document-specific stylesheet only some forms pull."""
    css = _read(repo_root, CSS)
    assert '.picker-field .choices__inner' in css
    assert 'border: 1px solid var(--border) !important' in css


def test_the_rule_is_not_left_duplicated_in_the_ap_stylesheet(repo_root):
    """Two copies of a treatment drift. The AP file keeps only a pointer."""
    ap = _read(repo_root, 'app/static/accounts_payable_form.css')
    assert '.picker-field .choices__inner {' not in ap
    assert 'MOVED to transactions.css' in ap


@pytest.mark.parametrize('template', PICKER_FORMS)
def test_a_form_with_a_picker_field_loads_that_stylesheet(repo_root, template):
    html = _read(repo_root, template)
    assert 'picker-field' in html, 'template no longer has a header picker'
    assert "filename='transactions.css'" in html, (
        'this form renders a .picker-field header picker but does not load the '
        'stylesheet that gives it a border -- the Receiving Report bug exactly')


def test_every_transactions_css_link_carries_the_same_cache_buster(repo_root):
    """A shared asset is linked from many forms. Bumping only the one you were
    looking at leaves the others serving a stale cached file -- the change then
    'does not show' on pages you never edited."""
    versions = set()
    for path in repo_root.joinpath('app').rglob('*.html'):
        for m in re.finditer(r"transactions\.css'\s*\)\s*}}\?v=(\d+)",
                             path.read_text(encoding='utf-8')):
            versions.add(m.group(1))
    assert len(versions) == 1, f'transactions.css served under mixed versions: {versions}'


def test_every_ap_stylesheet_link_carries_the_same_cache_buster(repo_root):
    versions = set()
    for path in repo_root.joinpath('app').rglob('*.html'):
        for m in re.finditer(r"accounts_payable_form\.css'\s*\)\s*}}\?v=(\d+)",
                             path.read_text(encoding='utf-8')):
            versions.add(m.group(1))
    assert len(versions) == 1, f'mixed versions: {versions}'


def test_the_receiving_report_form_renders_the_picker_and_the_stylesheet(
        client, staff_user, main_branch, db_session):
    """The end the user sees: one GET, both halves present. A file-level check
    alone would pass even if the route stopped rendering the form."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    if main_branch not in staff_user.branches.all():
        staff_user.branches.append(main_branch)
    perms = dict(staff_user.get_book_permissions() or {})
    perms.update({'receiving_reports': True, 'purchase_orders': True, 'products': True})
    staff_user.set_book_permissions(perms)
    db_session.commit()
    clear_module_config_cache()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(staff_user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = main_branch.id

    body = client.get('/receiving-reports/create').data.decode()
    assert 'picker-field' in body
    assert 'transactions.css' in body
