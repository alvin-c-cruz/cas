"""Bug report #7 (2 Nov 2026, CDV 1342E): "print buttons should also have bug reports."

The print pages are full HTML documents of their own -- they do not extend base.html -- so they
had no "Report a problem" button. Each now includes one shared partial: the button (screen only,
never on paper), the report script and stylesheet, and the CSRF token the script sends.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from tests.integration._bug_report_helpers import login

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]

APP_DIR = Path(__file__).resolve().parents[2] / 'app'
INCLUDE = "{% include '_print_report_button.html' %}"

# Full pages that rightly carry no print-page button: the layout itself, the signed-out pages,
# and the branch picker (it runs before a branch is chosen and has nothing to print).
NOT_PRINT_PAGES = {
    'templates/base.html',
    'users/templates/users/login.html',
    'users/templates/users/register.html',
    'users/templates/users/select_branch.html',
}


def _standalone_pages():
    pages = []
    for path in APP_DIR.rglob('*.html'):
        rel = path.relative_to(APP_DIR).as_posix()
        if rel.startswith('static/'):
            continue
        text = path.read_text(encoding='utf-8-sig')
        if '<html' in text.lower() and '{% extends' not in text:
            pages.append((rel, text))
    return pages


def test_there_are_standalone_print_pages_to_check():
    """Guards the scan below: if it found nothing it would pass vacuously."""
    assert len(_standalone_pages()) >= 40


@pytest.mark.parametrize('rel, text', _standalone_pages(), ids=lambda v: v if isinstance(v, str) and v.endswith('.html') else '')
def test_every_standalone_page_includes_the_report_button(rel, text):
    if rel in NOT_PRINT_PAGES:
        assert INCLUDE not in text
    else:
        assert INCLUDE in text, f'{rel} is a full page without the Report a problem button'


def _je(branch_id, cash, revenue):
    je = JournalEntry(entry_number='JV-2026-11-0001', entry_date=date(2026, 11, 2), description='Test',
                      reference='JV-2026-11-0001', entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True,
                      total_debit=Decimal('100'), total_credit=Decimal('100'))
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash.id,
                                    debit_amount=Decimal('100'), credit_amount=Decimal('0')))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=revenue.id,
                                    debit_amount=Decimal('0'), credit_amount=Decimal('100')))
    db.session.commit()
    return je


@pytest.fixture
def print_pages(main_branch, cash_account, revenue_account):
    je = _je(main_branch.id, cash_account, revenue_account)
    return ['/reports/trial-balance/print', f'/journal-entries/{je.id}/print']


def test_print_pages_carry_the_button_the_script_and_the_token(
        client, admin_user, main_branch, print_pages):
    login(client, admin_user, 'admin123', main_branch)
    for url in print_pages:
        resp = client.get(url)
        assert resp.status_code == 200, url
        html = resp.get_data(as_text=True)
        assert (f'<button type="button" class="cas-print-report" data-report-open '
                f'data-report-user="{admin_user.id}"') in html, url
        assert html.count('data-report-open') == 1, url
        assert 'aria-label="Report a problem"' in html, url
        assert '/static/js/bug-report.js' in html and 'data-endpoint="/bug-reports"' in html, url
        assert '/static/css/bug-report.css' in html, url
        assert '<meta name="csrf-token" content="' in html, url


def test_the_button_never_prints(client, admin_user, main_branch, print_pages):
    login(client, admin_user, 'admin123', main_branch)
    html = client.get(print_pages[0]).get_data(as_text=True)
    assert '@media print { .cas-print-report { display: none !important; } }' in html
