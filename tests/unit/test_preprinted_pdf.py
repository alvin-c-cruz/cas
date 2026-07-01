import pytest
from datetime import date
from io import BytesIO

from app import db
from app.preprinted_forms.models import PrintLayout
from app.preprinted_forms.pdf import render_preprinted
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.unit]


def _build_layout():
    pl = PrintLayout(voucher_type='JV', active=True, page_width_mm=215.9, page_height_mm=279.4)
    pl.set_fields([
        {'key': 'particulars', 'x_mm': 20, 'y_mm': 20, 'font_size': 10, 'align': 'L', 'visible': True},
        {'key': 'date', 'x_mm': 150, 'y_mm': 20, 'font_size': 10, 'align': 'L', 'visible': True},
        {'key': 'reference', 'x_mm': 20, 'y_mm': 30, 'font_size': 10, 'align': 'L', 'visible': False},
    ])
    pl.set_line_band({
        'anchor_y_mm': 80, 'row_height_mm': 6, 'max_rows': 12, 'font_size': 9,
        'columns': [
            {'key': 'account_name', 'x_mm': 15, 'width_mm': 60, 'align': 'L'},
            {'key': 'debit', 'x_mm': 120, 'width_mm': 30, 'align': 'R'},
        ],
    })
    return pl


def _build_entry(db_session, main_branch, cash_account, revenue_account):
    je = JournalEntry(
        entry_number='JV-2026-01-0099',
        entry_date=date(2026, 1, 15),
        description='₱ test description with peso sign',
        reference='HIDDEN-REF-VALUE',
        entry_type='adjustment',
        branch_id=main_branch.id,
        status='draft',
    )
    db.session.add(je)
    db.session.flush()

    line1 = JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash_account.id,
                              debit_amount=1234.56, credit_amount=0)
    line2 = JournalEntryLine(entry_id=je.id, line_number=2, account_id=revenue_account.id,
                              debit_amount=0, credit_amount=1234.56)
    db.session.add_all([line1, line2])
    db.session.commit()
    return je


def test_render_preprinted_returns_pdf_with_expected_values(db_session, main_branch, cash_account, revenue_account):
    layout = _build_layout()
    je = _build_entry(db_session, main_branch, cash_account, revenue_account)

    result = render_preprinted(layout, je)

    assert isinstance(result, bytes)
    assert result.startswith(b'%PDF')
    assert len(result) > 200

    from pypdf import PdfReader
    reader = PdfReader(BytesIO(result))
    text = ' '.join(page.extract_text() for page in reader.pages)
    normalized = ' '.join(text.split())

    # visible field: particulars (description, minus the stray peso sign)
    assert 'test description with peso sign' in normalized
    # neither the peso glyph nor a "PHP" replacement should appear
    assert '₱' not in normalized
    assert 'PHP' not in normalized

    # hidden field must not appear
    assert 'HIDDEN-REF-VALUE' not in normalized

    # both line rows' values present
    assert cash_account.name in normalized
    assert revenue_account.name in normalized
    assert '1,234.56' in normalized


def test_render_preprinted_test_mode_no_background_no_raise(db_session, main_branch, cash_account, revenue_account):
    layout = _build_layout()
    layout.background_image = 'does-not-exist.png'
    je = _build_entry(db_session, main_branch, cash_account, revenue_account)

    # test=True with a missing background image must not raise, and still
    # produces a valid PDF (no app context needed to succeed gracefully).
    result = render_preprinted(layout, je, test=True)
    assert result.startswith(b'%PDF')


def test_render_preprinted_respects_max_rows_cap(db_session, main_branch, cash_account, revenue_account):
    """Verify that max_rows: 2 truncates a 3-line entry to 2 rendered rows."""
    # Layout with max_rows: 2, single column
    pl = PrintLayout(voucher_type='JV', active=True, page_width_mm=215.9, page_height_mm=279.4)
    pl.set_fields([
        {'key': 'particulars', 'x_mm': 20, 'y_mm': 20, 'font_size': 10, 'align': 'L', 'visible': True},
    ])
    pl.set_line_band({
        'anchor_y_mm': 80, 'row_height_mm': 6, 'max_rows': 2, 'font_size': 9,
        'columns': [
            {'key': 'line_description', 'x_mm': 15, 'width_mm': 100, 'align': 'L'},
        ],
    })

    # Entry with 3 lines, each with distinct description
    je = JournalEntry(
        entry_number='JV-2026-01-0100',
        entry_date=date(2026, 1, 15),
        description='max_rows cap test',
        branch_id=main_branch.id,
        status='draft',
    )
    db.session.add(je)
    db.session.flush()

    line1 = JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash_account.id,
                              debit_amount=100, credit_amount=0, description='ROW-ONE')
    line2 = JournalEntryLine(entry_id=je.id, line_number=2, account_id=revenue_account.id,
                              debit_amount=0, credit_amount=50, description='ROW-TWO')
    line3 = JournalEntryLine(entry_id=je.id, line_number=3, account_id=cash_account.id,
                              debit_amount=0, credit_amount=50, description='ROW-THREE')
    db.session.add_all([line1, line2, line3])
    db.session.commit()

    result = render_preprinted(pl, je)

    from pypdf import PdfReader
    reader = PdfReader(BytesIO(result))
    text = ' '.join(page.extract_text() for page in reader.pages)
    normalized = ' '.join(text.split())

    # First two rows must be present
    assert 'ROW-ONE' in normalized
    assert 'ROW-TWO' in normalized
    # Third row must be absent due to max_rows: 2
    assert 'ROW-THREE' not in normalized


def test_render_preprinted_empty_field_value_no_raise(db_session, main_branch, cash_account, revenue_account):
    """Verify that visible left-aligned fields with empty values don't crash."""
    # Layout with reference field visible (normally hidden), left-aligned
    pl = PrintLayout(voucher_type='JV', active=True, page_width_mm=215.9, page_height_mm=279.4)
    pl.set_fields([
        {'key': 'particulars', 'x_mm': 20, 'y_mm': 20, 'font_size': 10, 'align': 'L', 'visible': True},
        # Reference is None in the entry, rendering to empty string; must not raise
        {'key': 'reference', 'x_mm': 20, 'y_mm': 30, 'font_size': 10, 'align': 'L', 'visible': True},
    ])
    pl.set_line_band({
        'anchor_y_mm': 80, 'row_height_mm': 6, 'max_rows': 12, 'font_size': 9,
        'columns': [
            {'key': 'account_name', 'x_mm': 15, 'width_mm': 60, 'align': 'L'},
        ],
    })

    je = JournalEntry(
        entry_number='JV-2026-01-0101',
        entry_date=date(2026, 1, 15),
        description='empty field test',
        reference=None,  # Explicitly None; resolves to empty string
        branch_id=main_branch.id,
        status='draft',
    )
    db.session.add(je)
    db.session.flush()

    line1 = JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash_account.id,
                              debit_amount=100, credit_amount=0)
    db.session.add(line1)
    db.session.commit()

    # Must not raise; the empty reference field is silently skipped
    result = render_preprinted(pl, je)
    assert isinstance(result, bytes)
    assert result.startswith(b'%PDF')

    from pypdf import PdfReader
    reader = PdfReader(BytesIO(result))
    text = ' '.join(page.extract_text() for page in reader.pages)
    normalized = ' '.join(text.split())

    # The non-empty particulars field must appear
    assert 'empty field test' in normalized
