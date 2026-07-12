"""Guard: the approve/reject/delete confirmation modals' .form-actions button
rows must be right-aligned (justify-content: flex-end), scoped by each
modal's unique id -- NOT via .modal-content or bare .form-actions, which
would also affect backup-modal (deferred) and every in-page form that
reuses .form-actions (vendors/form.html, customers/form.html, macros.html).
BUG-FEAT-MODAL-ACTIONS-CENTER."""
import re
from pathlib import Path
import pytest

pytestmark = [pytest.mark.unit]

CSS_PATH = Path('app/static/css/style.css')
BASE_PATH = Path('app/templates/base.html')

TARGET_MODAL_IDS = ['approve-modal', 'reject-modal', 'delete-modal']


def _css():
    return CSS_PATH.read_text(encoding='utf-8')


def _find_ruleset_containing(css, needle):
    """Return (selector_text, body) of the first {...} ruleset whose
    selector text (which may be a comma-separated list) contains `needle`."""
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
        selector, body = m.group(1), m.group(2)
        if needle in selector:
            return selector, body
    return None, None


@pytest.mark.parametrize('modal_id', TARGET_MODAL_IDS)
def test_target_modal_form_actions_are_right_aligned(modal_id):
    css = _css()
    selector, body = _find_ruleset_containing(css, f'#{modal_id} .form-actions')
    assert selector is not None, \
        f'#{modal_id} .form-actions must have an id-scoped rule in style.css'
    assert re.search(r'justify-content:\s*flex-end', body), \
        f'#{modal_id} .form-actions must set justify-content: flex-end'


def test_backup_modal_is_not_targeted_by_the_fix():
    css = _css()
    selector, _ = _find_ruleset_containing(css, '#backup-modal .form-actions')
    assert selector is None, \
        'backup-modal shares the same root cause but was explicitly deferred ' \
        '-- it must NOT be right-aligned by this change'


def test_class_based_selector_not_used():
    """A `.modal-content .form-actions` (or bare `.form-actions`) rule with
    justify-content:flex-end would also catch backup-modal and every
    in-page form that reuses .form-actions -- the fix must be id-scoped."""
    css = _css()
    assert '.modal-content .form-actions' not in css


def test_global_form_actions_default_is_unchanged():
    base = BASE_PATH.read_text(encoding='utf-8')
    m = re.search(r'(?<!#)\.form-actions\s*\{([^}]*)\}', base)
    assert m is not None, '.form-actions base rule not found in base.html -- template changed'
    assert 'justify-content' not in m.group(1), \
        'the global .form-actions default must stay unset (left-aligned) for in-page forms'
