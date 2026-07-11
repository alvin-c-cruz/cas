import pathlib
import pytest

pytestmark = [pytest.mark.integration]

APP = pathlib.Path(__file__).resolve().parents[2] / 'app'

# The four print views whose Close control was a redirecting anchor.
CLOSE_LAGGARDS = [
    'journal_entries/templates/journal_entries/print.html',
    'accounts_payable/templates/accounts_payable/print.html',
    'cash_disbursements/templates/cash_disbursements/print.html',
    'cash_receipts/templates/cash_receipts/print.html',
]


def _src(rel):
    return (APP / rel).read_text(encoding='utf-8')


def test_laggard_close_controls_use_window_close():
    for rel in CLOSE_LAGGARDS:
        src = _src(rel)
        assert 'onclick="window.close()"' in src, f'{rel}: Close should call window.close()'


def test_no_print_template_has_a_redirecting_close_anchor():
    """Drift pin: no print template anywhere may render Close as an anchor that
    navigates the print tab to a detail view (BUG-PRINT-CLOSE-NEWTAB-PARITY)."""
    offenders = [p.relative_to(APP).as_posix()
                 for p in APP.glob('*/templates/**/print*.html')
                 if 'class="btn-close" href' in p.read_text(encoding='utf-8')]
    assert offenders == [], f'redirecting Close anchor(s) still present: {offenders}'
