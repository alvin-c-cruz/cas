"""Drift-pin: every RowVersionFormMixin form MUST deliver its lost-update token.

BUG-DR-EDIT-FALSE-CONFLICT class: the optimistic-lock guard reads `row_version`
from the raw POST body (`submitted_version()` in app/utils/concurrency.py), so a
form whose template drops the field from the RENDER posts no token and
false-conflicts every edit. A form is safe if it renders `form.hidden_tag()`
(auto-emits every HiddenField incl. row_version) OR renders `form.row_version`
explicitly. A csrf-only form that does NEITHER is broken in the browser and
invisible to a test client that posts row_version directly.

This test pins the CLASS, not just the Delivery Receipt: it fails closed the next
time anyone drops `hidden_tag()` (e.g. to dodge a duplicate-field bug like
BUG-DR-DUP-LINES) on a RowVersionFormMixin form without hand-rendering the token.

Relies on the CAS convention `app/<feature>/forms.py` <-> the primary edit
template `app/<feature>/templates/<feature>/form.html`.
"""
import re
import pytest
from pathlib import Path

from app.utils.concurrency import RowVersionFormMixin

_JINJA_COMMENT = re.compile(r'\{#.*?#\}', re.DOTALL)


def _renders(content, needle):
    """True if `needle` appears in template OUTPUT, not just a {# comment #}.

    The DR template's own comment says `NOT form.hidden_tag()`, so a raw
    substring scan would match the comment and mask a dropped render.
    """
    return needle in _JINJA_COMMENT.sub('', content)

pytestmark = pytest.mark.integration


def _all_rowversion_form_classes():
    """Every (transitive) RowVersionFormMixin subclass currently imported that is
    defined under app.* -- test-defined subclasses (e.g. a _VersionedForm in
    tests.unit.test_concurrency) are excluded: they have no product form template
    and are not this test's regression target (a real form template dropping its
    hidden token), yet they leak into __subclasses__() under full-suite ordering."""
    seen = []
    stack = list(RowVersionFormMixin.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls not in seen:
            seen.append(cls)
            stack.extend(cls.__subclasses__())
    return [cls for cls in seen if cls.__module__.startswith('app.')]


def test_every_rowversion_form_template_delivers_the_token(app):
    """Uses the `app` fixture so create_app has imported every blueprint's forms,
    populating RowVersionFormMixin.__subclasses__()."""
    app_root = Path(__file__).resolve().parents[2] / 'app'
    classes = _all_rowversion_form_classes()
    # Guard against an empty walk silently passing (e.g. imports not triggered).
    assert classes, 'no RowVersionFormMixin subclasses discovered -- app not imported?'

    offenders = []
    checked = []
    for cls in classes:
        # app.delivery_receipts.forms -> feature 'delivery_receipts'
        parts = cls.__module__.split('.')
        assert parts[0] == 'app' and parts[-1] == 'forms', \
            f'{cls.__name__} lives in unexpected module {cls.__module__}'
        feature = parts[1]
        template = app_root / feature / 'templates' / feature / 'form.html'
        if not template.exists():
            offenders.append(f'{cls.__name__}: no form template at {template.relative_to(app_root.parent)}')
            continue
        content = template.read_text(encoding='utf-8')
        renders_token = _renders(content, 'form.hidden_tag()') or _renders(content, 'form.row_version')
        checked.append((cls.__name__, feature))
        if not renders_token:
            offenders.append(
                f'{cls.__name__} ({feature}/form.html): renders neither form.hidden_tag() '
                f'nor form.row_version -- lost-update token is dropped from the POST '
                f'(BUG-DR-EDIT-FALSE-CONFLICT class)')

    assert not offenders, 'RowVersionFormMixin forms missing their token:\n  ' + '\n  '.join(offenders)
    # Sanity: the known documents must have been exercised, not skipped.
    features = {f for _, f in checked}
    assert 'delivery_receipts' in features, f'DR not among checked forms: {sorted(features)}'
