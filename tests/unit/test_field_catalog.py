import pytest
from datetime import date
from decimal import Decimal
from app.preprinted_forms.field_catalog import (FIELD_CATALOG, resolve_field, amount_in_words)

pytestmark = [pytest.mark.unit]

def test_all_voucher_types_have_catalog():
    for vt in ('SI', 'CR', 'CD', 'AP', 'JV'):
        cat = FIELD_CATALOG[vt]
        assert cat['header'] and 'line_columns' in cat
        for f in cat['header'] + cat['line_columns']:
            assert callable(f['resolve']) and f['key'] and f['label']

def test_amount_in_words_peso():
    assert amount_in_words(Decimal('1234.50')).lower().startswith('one thousand two hundred thirty')
    assert 'peso' in amount_in_words(Decimal('1.00')).lower()
    assert amount_in_words(Decimal('0')).lower().startswith('zero')

def test_resolve_jv_number_uses_display_number(db_with_data, main_branch):
    from app.journal_entries.models import JournalEntry
    from app import db
    je = JournalEntry(entry_number='JV-2026-01-0001', entry_date=date(2026, 1, 1), description='Test',
                      entry_type='adjustment', branch_id=main_branch.id, status='draft')
    db.session.add(je); db.session.flush()
    assert resolve_field('JV', 'number', je) == 'JV-2026-01-0001'
