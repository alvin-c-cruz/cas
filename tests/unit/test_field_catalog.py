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

@pytest.mark.parametrize("value,expected", [
    (Decimal("1.00"),    "One Peso and 00/100"),
    (Decimal("2.00"),    "Two Pesos and 00/100"),
    (Decimal("0.00"),    "Zero Pesos and 00/100"),
    (Decimal("0.05"),    "Zero Pesos and 05/100"),
    (Decimal("0.99"),    "Zero Pesos and 99/100"),
    (Decimal("100.00"),  "One Hundred Pesos and 00/100"),
    (Decimal("1000.00"), "One Thousand Pesos and 00/100"),
    (Decimal("1001.00"), "One Thousand One Pesos and 00/100"),
    (Decimal("1234.50"), "One Thousand Two Hundred Thirty-Four Pesos and 50/100"),
    (Decimal("1000000.00"),     "One Million Pesos and 00/100"),
    (Decimal("1000000000.00"),  "One Billion Pesos and 00/100"),
    (Decimal("21.00"),   "Twenty-One Pesos and 00/100"),
    (Decimal("999999999999.99"), "Nine Hundred Ninety-Nine Billion Nine Hundred Ninety-Nine "
                                 "Million Nine Hundred Ninety-Nine Thousand Nine Hundred "
                                 "Ninety-Nine Pesos and 99/100"),
])
def test_amount_in_words_boundaries(value, expected):
    assert amount_in_words(value) == expected

def test_amount_in_words_trillion_not_blank():
    out = amount_in_words(Decimal("1000000000000.00"))  # was: swallowed IndexError -> blank line
    assert out.startswith("One Trillion")
    assert out.endswith("00/100")

def test_amount_in_words_half_up():
    assert amount_in_words(Decimal("0.005")) == "Zero Pesos and 01/100"

def test_resolve_jv_number_uses_display_number(db_with_data, main_branch):
    from app.journal_entries.models import JournalEntry
    from app import db
    je = JournalEntry(entry_number='JV-2026-01-0001', entry_date=date(2026, 1, 1), description='Test',
                      entry_type='adjustment', branch_id=main_branch.id, status='draft')
    db.session.add(je); db.session.flush()
    assert resolve_field('JV', 'number', je) == 'JV-2026-01-0001'
