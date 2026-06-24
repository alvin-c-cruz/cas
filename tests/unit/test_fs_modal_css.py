"""Guard: the FS ledger modal must be hideable.

The modal is shown via `.fs-modal-backdrop { display: flex }`. The JS hides it
by toggling the `hidden` attribute — but a bare class selector overrides the
UA `[hidden] { display:none }` rule, so without a higher-specificity
`.fs-modal-backdrop[hidden] { display:none }` the modal renders on page load
and can never be closed (BUG: stuck empty popup on IS/BS/CF).
"""
import re
from pathlib import Path
import pytest

pytestmark = [pytest.mark.unit]


def test_modal_backdrop_hidden_overrides_display():
    css = Path('app/static/css/style.css').read_text(encoding='utf-8')
    m = re.search(r'\.fs-modal-backdrop\[hidden\]\s*\{([^}]*)\}', css)
    assert m, 'missing .fs-modal-backdrop[hidden] rule — modal cannot be hidden'
    body = m.group(1)
    assert re.search(r'display\s*:\s*none', body), \
        '.fs-modal-backdrop[hidden] must set display:none'
