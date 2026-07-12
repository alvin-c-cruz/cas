"""Guard: the Pending Approvals Reason column must be narrow and truncated
so the Actions column (View/Approve/Reject) fits inside the page's
horizontal-scroll wrapper without clipping the Reject button.
BUG-PENDING-APPROVALS-ACTIONS-OVERFLOW."""
import re
from pathlib import Path
import pytest

pytestmark = [pytest.mark.unit]

TEMPLATE = Path('app/accounts/templates/accounts/pending_approvals.html')


def _reason_cell_line():
    tpl = TEMPLATE.read_text(encoding='utf-8')
    m = re.search(r'<td[^>]*>\{\{ request\.request_reason[^\n]*', tpl)
    assert m is not None, 'Reason <td> not found -- template structure changed'
    return m.group(0)


def test_reason_column_is_narrower_than_240px():
    line = _reason_cell_line()
    m = re.search(r'max-width:\s*(\d+)px', line)
    assert m is not None, 'Reason <td> must declare a max-width'
    width = int(m.group(1))
    assert width <= 150, \
        f'Reason column max-width is {width}px -- must be <=150px to reclaim ' \
        f'the ~109-136px the Actions column needs (BUG-PENDING-APPROVALS-ACTIONS-OVERFLOW)'


def test_reason_column_actually_truncates():
    line = _reason_cell_line()
    assert 'white-space: nowrap' in line or 'white-space:nowrap' in line, \
        'without white-space:nowrap, long reason text wraps instead of truncating'
    assert 'overflow: hidden' in line or 'overflow:hidden' in line
    assert 'text-overflow: ellipsis' in line or 'text-overflow:ellipsis' in line


def test_reason_column_has_hover_title_with_full_text():
    line = _reason_cell_line()
    assert 'title="{{ request.request_reason' in line, \
        'truncated text must still be readable via a title tooltip'
