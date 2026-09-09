"""The voucher JE face prints one row per account per side.

Owner, 2026-09-09: a voucher whose expense lines all hit the same account
printed that account title once per source line, filling the pre-printed
journal-entry face with the same title repeated.

PER SIDE, NEVER NETTED. An account carrying both a debit and a credit keeps
both rows -- netting would make the printed totals disagree with the posted
entry, and tying to the books is the whole purpose of this face.

These are the RENDERED assertions. The rule itself is unit-tested in
tests/unit/test_je_display_merge.py; what is checked here is that the voucher
routes actually apply it and that the printed page reflects it.
"""
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration]


def _row_for(band, code):
    """The single <tr> whose first cell is this account code."""
    import re
    rows = [r for r in re.findall(r'<tr .*?</tr>', band, re.S)
            if f'<td>{code}</td>' in r]
    assert len(rows) == 1, 'expected exactly one row for %s, got %d' % (code,
                                                                       len(rows))
    return rows[0]


def _band(html, name):
    """The markup of ONE journal-entry band.

    The overlay renders all three bands every time -- combined, debit and
    credit -- and lets CSS show whichever the layout selected. So a debit
    account's code legitimately appears TWICE in the page (combined + debit),
    and a page-wide count could never fall to one however well the merge
    worked. Every assertion below is scoped to a single band for that reason.
    """
    import re
    m = re.search(r'data-je="%s".*?<table class="pp-je-table">(.*?)</table>'
                  % name, html, re.S)
    assert m, 'the %s band did not render' % name
    return m.group(1)


def _je_with_two_legs_on_one_account(db_session, main_branch, make_account,
                                     entry_number):
    """Dr Freight 1,000 + Dr Freight 1,500 + Cr Payable 2,500.

    The two debits are SEPARATE legs on ONE account -- exactly the shape the
    owner reported, and the shape that used to print 'Freight' twice.
    """
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    je = JournalEntry(entry_number=entry_number, entry_date=date(2026, 9, 9),
                      description='same-account legs', branch_id=main_branch.id,
                      total_debit=Decimal('2500.00'),
                      total_credit=Decimal('2500.00'),
                      is_balanced=True, status='posted')
    db_session.add(je); db_session.commit()
    freight, payable = make_account('19101'), make_account('29101')
    for n, amt in ((1, '1000.00'), (2, '1500.00')):
        db_session.add(JournalEntryLine(
            entry_id=je.id, line_number=n, account_id=freight.id,
            debit_amount=Decimal(amt), credit_amount=Decimal('0.00')))
    db_session.add(JournalEntryLine(
        entry_id=je.id, line_number=3, account_id=payable.id,
        debit_amount=Decimal('0.00'), credit_amount=Decimal('2500.00')))
    db_session.commit()
    return je, freight, payable


@pytest.fixture
def apv_face(client, db_session, admin_user, main_branch, make_account,
             login_user):
    """A posted APV whose entry carries two debit legs on one account.

    Built here rather than looked up: a `query.first()` fixture that finds
    nothing skips every assertion and proves nothing.
    """
    from app.accounts_payable.models import AccountsPayable
    from app.vendors.models import Vendor
    from app.settings import AppSettings
    # A REAL login, not a forged session -- Flask-Login memoises the resolved
    # user on g._login_user and conftest keeps one app context for the whole
    # test, so a hand-written _user_id does not authenticate here.
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    AppSettings.set_setting('ap_print_form', 'preprinted')
    AppSettings.set_setting('apv_print_access', 'draft_and_posted')

    v = Vendor(code='MRG-V', name='Merge Vendor')
    db_session.add(v); db_session.commit()
    je, freight, payable = _je_with_two_legs_on_one_account(
        db_session, main_branch, make_account, 'MRG-JE-1')
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='MRG-AP-1',
                         ap_date=date(2026, 9, 9), due_date=date(2026, 10, 9),
                         payee_type='vendor', payee_id=v.id, vendor_id=v.id,
                         vendor_name=v.name, notes='', status='posted',
                         journal_entry_id=je.id)
    db_session.add(ap); db_session.commit()
    resp = client.get(f'/accounts-payable/{ap.id}/print')
    assert resp.status_code == 200, (
        'the APV overlay did not render (-> %s); every assertion would be '
        'vacuous' % resp.headers.get('Location'))
    return resp.get_data(as_text=True), freight, payable


class TestTheAPVFace:

    def test_the_repeated_account_prints_once(self, apv_face):
        html, freight, _ = apv_face
        band = _band(html, 'combined')
        # Two source legs hit this account; before the merge it printed twice.
        assert band.count(f'<td>{freight.code}</td>') == 1
        # And the band holds exactly two rows now: the merged debit, the credit.
        assert band.count('<tr ') == 2

    def test_the_merged_row_carries_the_SUM(self, apv_face):
        """The positive half, scoped to the FREIGHT row specifically.

        Asserting merely that '2,500.00' appears somewhere would not
        discriminate: the credit leg is also 2,500.00, so that assertion passes
        even with merging switched off. Verified by disabling the merge and
        watching this test keep passing -- which is why it now reads the row."""
        html, freight, _ = apv_face
        row = _row_for(_band(html, 'combined'), freight.code)
        assert '2,500.00' in row

    def test_the_unmerged_component_amounts_are_gone(self, apv_face):
        html, _, _ = apv_face
        band = _band(html, 'combined')
        assert '1,000.00' not in band
        assert '1,500.00' not in band

    def test_the_other_account_still_prints(self, apv_face):
        """Control: merging must not swallow a different account."""
        html, _, payable = apv_face
        assert f'<td>{payable.code}</td>' in _band(html, 'combined')

    def test_the_face_still_ties(self, apv_face):
        """Merging is per side, so the entry that balanced before still
        balances -- the face must NOT print its unbalanced notice."""
        html, _, _ = apv_face
        assert 'JOURNAL ENTRY UNBALANCED' not in html


@pytest.fixture
def cdv_face(client, db_session, admin_user, main_branch, make_account,
             login_user):
    """The same shape on a cash disbursement voucher."""
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.vendors.models import Vendor
    from app.settings import AppSettings
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    AppSettings.set_setting('cd_print_form', 'preprinted')

    v = Vendor(code='MRG-V2', name='Merge Vendor CDV')
    db_session.add(v); db_session.commit()
    je, freight, payable = _je_with_two_legs_on_one_account(
        db_session, main_branch, make_account, 'MRG-JE-2')
    cash = make_account('10101')   # cash_account_id is NOT NULL on this model
    cdv = CashDisbursementVoucher(
        cash_account_id=cash.id,
        branch_id=main_branch.id, cdv_number='MRG-CDV-1',
        cdv_date=date(2026, 9, 9), vendor_id=v.id, vendor_name=v.name,
        status='posted', journal_entry_id=je.id)
    db_session.add(cdv); db_session.commit()
    resp = client.get(f'/cash-disbursements/{cdv.id}/print')
    assert resp.status_code == 200, (
        'the CDV overlay did not render (-> %s)' % resp.headers.get('Location'))
    return resp.get_data(as_text=True), freight, payable


class TestTheCDVFace:

    def test_the_repeated_account_prints_once(self, cdv_face):
        html, freight, _ = cdv_face
        band = _band(html, 'combined')
        assert band.count(f'<td>{freight.code}</td>') == 1
        assert band.count('<tr ') == 2

    def test_the_merged_row_carries_the_SUM(self, cdv_face):
        html, freight, _ = cdv_face
        assert '2,500.00' in _row_for(_band(html, 'combined'), freight.code)

    def test_the_face_still_ties(self, cdv_face):
        html, _, _ = cdv_face
        assert 'JOURNAL ENTRY UNBALANCED' not in html
