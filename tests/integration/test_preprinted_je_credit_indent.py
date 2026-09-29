"""Credit legs are indented on every pre-printed journal-entry face.

Owner, 2026-09-29, looking at APV 00030's pre-printed print: "the printable AP
should have indented credit entries. all pre-printed layout's JE should be like
this." A journal entry written by hand sets its credits a step to the right of
its debits; the faces printed them flush left, so debits and credits read as one
undifferentiated stack.

THREE faces draw an entry onto pre-printed stock and all three take the rule:
the APV and CDV journal-entry faces (column face + combined grid) and the JV
line band, whose lines ARE the entry. One class, `pp-je-cr`, on the account
code/title cell of a credit row, backed by one rule (`text-indent`) so the
amount columns and the row heights -- the alignment invariant the faces rest
on -- are untouched. The separated credit band is deliberately left alone: it
is its own box on the stationery, so an indent inside it would only pull the
text off the box.

A leg carrying BOTH a debit and a credit is not a credit row and is not
indented; that shape is not produced by any posting path here and guessing at
it would be wrong either way.
"""
import re

import pytest

from app.settings import AppSettings
from tests.integration.test_cdv_print_form import _cdv_with_je, login
from tests.integration.test_jv_preprinted import _login, _posted_jv

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable,
              pytest.mark.cash_disbursements, pytest.mark.journal_entries]

RULE = '.pp-je-cr { text-indent:'


def _column_cells(html, attr, key):
    """The class attribute of every cell in ONE positioned column, in row order.

    The column is the `<div ... data-jecol="key">` (JE face) or `data-col="key"`
    (JV band) element; its cells run until the next column starts.
    """
    needle = '%s="%s"' % (attr, key)
    assert needle in html, needle
    seg = html.split(needle, 1)[1]
    nxt = re.search(r'<div class="pp-(?:jecol|col)\b', seg)
    if nxt:
        seg = seg[:nxt.start()]
    return re.findall(r'<div class="(pp-cell[^"]*)"', seg)


def _combined_rows(html):
    """The rows of the combined grid: a list of (code_td_attrs, name_td_attrs)."""
    seg = html.split('data-je="combined"', 1)[1].split('</table>', 1)[0]
    return re.findall(r'<tr[^>]*><td([^>]*)>[^<]*</td><td([^>]*)>', seg)


# --------------------------------------------------------------------------- APV

@pytest.fixture
def apv_overlay(client, db_session, admin_user, main_branch, make_account, login_user):
    """An APV whose entry is Dr 19001 100 / Cr 29001 100, printed on the
    pre-printed face with the column face ON (the combined grid renders too,
    inactive, which is how the designer previews the toggle)."""
    from datetime import date
    from decimal import Decimal
    from app.accounts_payable.models import AccountsPayable
    from app.accounts_payable.preprinted_layout import get_layout, save_layout
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.vendors.models import Vendor

    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    AppSettings.set_setting('ap_print_form', 'preprinted')
    AppSettings.set_setting('apv_print_access', 'draft_and_posted')

    v = Vendor(code='CRI-V', name='Credit Indent Vendor')
    db_session.add(v); db_session.commit()
    je = JournalEntry(entry_number='CRI-0001', entry_date=date(2026, 9, 29),
                      description='APV JE', branch_id=main_branch.id,
                      total_debit=Decimal('100.00'), total_credit=Decimal('100.00'),
                      is_balanced=True, status='posted')
    db_session.add(je); db_session.commit()
    dr, cr = make_account('19001'), make_account('29001')
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=dr.id,
                                    debit_amount=Decimal('100.00'),
                                    credit_amount=Decimal('0.00')))
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=cr.id,
                                    debit_amount=Decimal('0.00'),
                                    credit_amount=Decimal('100.00')))
    db_session.commit()
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='CRI-AP-1',
                         ap_date=date(2026, 9, 29), due_date=date(2026, 10, 29),
                         payee_type='vendor', payee_id=v.id,
                         vendor_id=v.id, vendor_name=v.name,
                         notes='', status='posted', journal_entry_id=je.id)
    db_session.add(ap); db_session.commit()

    lay = get_layout(ap.branch_id)
    lay['journalEntry']['columnsEnabled'] = True
    save_layout(lay, admin_user.username, ap.branch_id)
    db_session.commit()
    resp = client.get(f'/accounts-payable/{ap.id}/print')
    assert resp.status_code == 200, resp.headers.get('Location')
    return resp.get_data(as_text=True)


class TestTheApvFace:

    def test_the_rule_is_real(self, apv_overlay):
        assert RULE in apv_overlay

    def test_the_credit_row_is_indented_in_the_title_column(self, apv_overlay):
        cells = _column_cells(apv_overlay, 'data-jecol', 'account_title')
        assert cells == ['pp-cell', 'pp-cell pp-je-cr'], cells

    def test_the_credit_row_is_indented_in_the_code_column(self, apv_overlay):
        cells = _column_cells(apv_overlay, 'data-jecol', 'account_code')
        assert cells == ['pp-cell', 'pp-cell pp-je-cr'], cells

    def test_the_amount_columns_are_never_indented(self, apv_overlay):
        """The indent lives on the text cells only; an indented amount cell would
        push a figure out of its printed box."""
        for key in ('debit', 'credit'):
            cells = _column_cells(apv_overlay, 'data-jecol', key)
            assert cells == ['pp-cell', 'pp-cell'], (key, cells)

    def test_the_combined_grid_indents_the_same_row(self, apv_overlay):
        rows = _combined_rows(apv_overlay)
        assert rows == [('', ''), (' class="pp-je-cr"', ' class="pp-je-cr"')], rows

    def test_the_separated_credit_band_is_left_alone(self, apv_overlay):
        seg = apv_overlay.split('data-je="credit"', 1)[1].split('</table>', 1)[0]
        assert 'pp-je-cr' not in seg


# --------------------------------------------------------------------------- CDV

@pytest.fixture
def cdv_overlay(client, db_session, admin_user, main_branch):
    """_cdv_with_je: Dr Utilities 5,000 + Dr Input VAT 600 ; Cr WHT 100 + Cr Cash 5,500
    -- two credit rows, so the rule is seen to apply per row, not just to the last one."""
    from app.cash_disbursements.preprinted_layout import get_layout, save_layout
    cdv = _cdv_with_je(db_session, main_branch)
    AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
    lay = get_layout(main_branch.id)
    lay['journalEntry']['columnsEnabled'] = True
    save_layout(lay, 'admin', main_branch.id)
    db_session.commit()
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get(f'/cash-disbursements/{cdv.id}/print')
    assert resp.status_code == 200, resp.headers.get('Location')
    return resp.get_data(as_text=True)


class TestTheCdvFace:

    def test_the_rule_is_real(self, cdv_overlay):
        assert RULE in cdv_overlay

    def test_both_credit_rows_are_indented_and_no_debit_row_is(self, cdv_overlay):
        cells = _column_cells(cdv_overlay, 'data-jecol', 'account_title')
        assert cells == ['pp-cell', 'pp-cell', 'pp-cell pp-je-cr', 'pp-cell pp-je-cr'], cells

    def test_the_amount_columns_are_never_indented(self, cdv_overlay):
        for key in ('debit', 'credit'):
            assert 'pp-je-cr' not in ''.join(_column_cells(cdv_overlay, 'data-jecol', key)), key

    def test_the_combined_grid_indents_the_same_rows(self, cdv_overlay):
        rows = _combined_rows(cdv_overlay)
        assert [r[1] for r in rows] == ['', '', ' class="pp-je-cr"', ' class="pp-je-cr"'], rows


# --------------------------------------------------------------------------- JV

@pytest.fixture
def jv_overlay(client, db_session, admin_user, main_branch):
    """A JV's lines ARE the entry: the line band takes the same rule."""
    AppSettings.set_setting('jv_print_form', 'preprinted')
    entry = _posted_jv(db_session, main_branch, admin_user)
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/journal-entries/{entry.id}/print')
    assert resp.status_code == 200, resp.headers.get('Location')
    return resp.get_data(as_text=True)


class TestTheJvBand:

    def test_the_rule_is_real(self, jv_overlay):
        assert RULE in jv_overlay

    def test_the_credit_line_is_indented_in_code_and_title(self, jv_overlay):
        for key in ('account_code', 'account_title'):
            cells = _column_cells(jv_overlay, 'data-col', key)
            assert cells == ['pp-cell', 'pp-cell pp-je-cr'], (key, cells)

    def test_the_other_columns_are_never_indented(self, jv_overlay):
        for key in ('line_number', 'debit', 'credit'):
            cells = _column_cells(jv_overlay, 'data-col', key)
            assert cells == ['pp-cell', 'pp-cell'], (key, cells)
