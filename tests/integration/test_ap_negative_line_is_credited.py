"""A negative AP line CREDITS its account.

Owner, 2026-09-10: "NEGATIVE ENTRY SHOULD BE CREDITTED", reported from a
payroll voucher -- gross wages debit the labour expense, and the employee's
HDMF loan repayment credits the loan payable on the same bill.

The bill refused it outright ("enter an amount greater than zero"), so the
voucher could not be saved at all; and had it saved, the posting wrote
debit_amount=net_base unconditionally, leaving a journal entry line carrying a
NEGATIVE DEBIT -- which no ledger report expects and which the JE face rendered
as a blank cell.

The cash disbursement voucher has always allowed this, with the rule mirrored
here: a negative line is BARE -- no VAT, no withholding. Extracting VAT from it
would invent a negative input tax the BIR return has no place for, and
withholding on it would refund tax that was never withheld.
"""
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayableItem

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


class TestTheLineModel:

    @pytest.fixture(autouse=True)
    def _app(self, db_session):
        """The SQLAlchemy mappers need the app configured before a model can be
        instantiated at all -- without this every test here dies on 'failed to
        locate a name (Vendor)' rather than on its own assertion."""
        return db_session

    def _line(self, amount, vat_rate=None, wt_rate=None):
        li = AccountsPayableItem(line_number=1, description='x',
                                 amount=Decimal(str(amount)),
                                 vat_rate=vat_rate, wt_rate=wt_rate)
        li.calculate_amounts()
        return li

    def test_a_negative_line_carries_no_vat(self):
        li = self._line('-3382.04', vat_rate=Decimal('12'))
        assert li.vat_amount == Decimal('0.00')

    def test_a_negative_line_carries_no_withholding(self):
        li = self._line('-3382.04', wt_rate=Decimal('2'))
        assert li.wt_amount == Decimal('0.00')

    def test_the_negative_amount_itself_survives(self):
        li = self._line('-3382.04')
        assert li.line_total == Decimal('-3382.04')

    def test_a_positive_line_still_extracts_vat(self):
        """CONTROL: the ordinary path is untouched. Without this, zeroing VAT
        everywhere would pass every assertion above."""
        li = self._line('1120.00', vat_rate=Decimal('12'))
        assert li.vat_amount == Decimal('120.00')

    def test_a_positive_line_still_withholds(self):
        li = self._line('1000.00', wt_rate=Decimal('2'))
        assert li.wt_amount == Decimal('20.00')


class TestWhatValidationAccepts:

    def test_zero_is_still_refused(self):
        """A zero line says nothing and posts nothing."""
        import re
        src = open('app/accounts_payable/views.py', encoding='utf-8').read()
        assert "if amount == 0:" in src
        assert 'must not be zero' in src

    def test_the_old_greater_than_zero_rule_is_gone(self):
        src = open('app/accounts_payable/views.py', encoding='utf-8').read()
        assert 'must be greater than zero' not in src

    def test_the_browser_agrees_with_the_server(self):
        """Both sides must accept the same thing, or the user is blocked by
        whichever is stricter -- here it was the browser."""
        src = open('app/accounts_payable/templates/accounts_payable/form.html',
                   encoding='utf-8').read()
        assert 'amount other than zero' in src
        assert 'enter an amount greater than zero' not in src


class TestThePosting:

    def test_a_negative_net_posts_as_a_credit(self):
        src = open('app/accounts_payable/views.py', encoding='utf-8').read()
        block = src[src.index('if net_base < ZERO:'):]
        block = block[:block.index('entry_line = JournalEntryLine')]
        assert 'dr, cr = ZERO, abs(net_base)' in block

    def test_the_journal_line_uses_those_two_values(self):
        """Guards the wiring, not just the arithmetic: computing dr/cr and then
        still writing net_base would pass the test above."""
        src = open('app/accounts_payable/views.py', encoding='utf-8').read()
        i = src.index('if net_base < ZERO:')
        block = src[i:i + 1200]
        assert 'debit_amount=dr' in block and 'credit_amount=cr' in block
