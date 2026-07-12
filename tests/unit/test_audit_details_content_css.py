"""Guard: .details-content must not be a display:grid container.

BUG-AUDITLOG-DETAILS-NESTED-GRID-COLLAPSE: .details-content (outer, wraps the
field grid + Notes + metadata footer in audit_log.html) and .details-grid
(inner, wraps the individual key/value field boxes) were BOTH
display:grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)).
Because .details-grid is the only field-bearing child of .details-content,
the outer grid's auto-fit collapsed to a single ~284px track, leaving the
inner grid only that much width to lay out its own columns -- so all 7+
audit-log fields stacked into one narrow column instead of a responsive
3-column grid.

.details-content's role is to stack its structurally distinct children
(the fields grid, an optional Notes block, the metadata footer) vertically,
not to compete with .details-grid for grid tracks -- it must not itself be
a multi-column grid. .details-grid is the one that should stay a real grid.
"""
import re
from pathlib import Path
import pytest

pytestmark = [pytest.mark.unit]


def _top_level_rule(css, selector):
    """First (non-media-query) `selector { ... }` block's body."""
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    assert m is not None, f'{selector} must be defined in style.css'
    return m.group(1)


def test_details_content_is_not_a_nested_grid():
    css = Path('app/static/css/style.css').read_text(encoding='utf-8')
    body = _top_level_rule(css, '.details-content')
    assert 'display: grid' not in body and 'display:grid' not in body, \
        '.details-content must not be display:grid -- it collapses .details-grid ' \
        'into a single track (BUG-AUDITLOG-DETAILS-NESTED-GRID-COLLAPSE)'


def test_details_grid_is_still_the_real_grid():
    css = Path('app/static/css/style.css').read_text(encoding='utf-8')
    body = _top_level_rule(css, '.details-grid')
    assert 'display: grid' in body or 'display:grid' in body, \
        '.details-grid must remain the actual responsive field grid'
    assert 'auto-fit' in body
