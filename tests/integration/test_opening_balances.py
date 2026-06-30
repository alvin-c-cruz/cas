import pytest
from app import db
from app.journals.views import VOUCHER_TYPES
from app.reports.general_journal_data import VOUCHER_ENTRY_TYPES

pytestmark = [pytest.mark.integration]


def test_opening_balance_is_a_registered_voucher_type():
    assert 'opening_balance' in VOUCHER_TYPES
    assert 'opening_balance' in VOUCHER_ENTRY_TYPES
