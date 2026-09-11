"""The purchase order offers VAT Exempt and Non-VAT, and charges no VAT on them.

Owner's handwritten note (2026-09-07, /purchase-orders/create): the treatment
dropdown should read

    Vat Inclusive / Vat Exclusive / Vat Exempt / Vat Zero Rated / Non Vat

THE TRAP this is written around: calculate_totals() ends in `else:  # inclusive`,
so any value it does not recognise falls into the INCLUSIVE branch. Adding the
two options to the dropdown without touching the calculation would have charged
VAT on an exempt order -- silently, with the header still reading "VAT Exempt".
That is a tax error on a document sent to a vendor, so the calculation is pinned
here first and the dropdown second.

Exempt and Non-VAT both carry no VAT. They are distinct BIR classifications --
an exempt transaction is outside VAT by law, a non-VAT supplier is not
registered for it -- but for the arithmetic on a purchase order, which is an
operational document with no GL effect, both mean the same thing: gross is the
total and there is no input tax to extract.
"""
from decimal import Decimal

import pytest

from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem, VAT_TREATMENTS

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _po(treatment, amount='1120.00', vat='120.00'):
    po = PurchaseOrder(po_number='VT-1', vat_treatment=treatment)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, quantity=Decimal('1'),
        unit_price=Decimal(str(amount)), amount=Decimal(str(amount)),
        vat_amount=Decimal(str(vat))))
    po.calculate_totals()
    return po


class TestTheNewTreatmentsChargeNoVat:

    def test_exempt_charges_no_vat(self, db_session):
        po = _po('exempt')
        assert po.vat_amount == Decimal('0.00')

    def test_non_vat_charges_no_vat(self, db_session):
        po = _po('non_vat')
        assert po.vat_amount == Decimal('0.00')

    def test_exempt_totals_the_gross(self, db_session):
        po = _po('exempt')
        assert po.subtotal == Decimal('1120.00')
        assert po.total_amount == Decimal('1120.00')

    def test_non_vat_totals_the_gross(self, db_session):
        po = _po('non_vat')
        assert po.total_amount == Decimal('1120.00')

    def test_they_do_NOT_fall_through_to_inclusive(self, db_session):
        """THE regression this file exists for. Under the old `else: # inclusive`
        the line's own 120.00 vat_amount was summed onto an exempt order."""
        for treatment in ('exempt', 'non_vat'):
            po = _po(treatment)
            assert po.vat_amount != Decimal('120.00'), treatment


class TestTheExistingTreatmentsAreUntouched:
    """Controls. Without these, zeroing VAT everywhere would pass the class
    above while quietly breaking every ordinary order."""

    def test_inclusive_still_extracts_the_lines_vat(self, db_session):
        po = _po('inclusive')
        assert po.vat_amount == Decimal('120.00')
        assert po.total_amount == Decimal('1120.00')

    def test_exclusive_still_adds_vat_on_top(self, db_session):
        po = _po('exclusive', amount='1000.00', vat='0.00')
        assert po.vat_amount == Decimal('120.00')
        assert po.total_amount == Decimal('1120.00')

    def test_zero_rated_still_charges_none(self, db_session):
        po = _po('zero_rated')
        assert po.vat_amount == Decimal('0.00')


class TestAnUnknownValueCannotSilentlyChargeVat:

    def test_the_fallback_is_explicit_about_inclusive(self, db_session):
        """A value that is not a recognised treatment must not be computed as
        VAT-inclusive by accident. `inclusive` stays the default for a document
        that names it; anything else is a bug, and a bug that charges tax should
        not be the quiet path."""
        po = _po('something_new')
        assert po.vat_amount == Decimal('0.00'), (
            'an unrecognised treatment fell into the inclusive branch and '
            'charged VAT')


class TestTheDropdown:

    def test_all_five_values_are_registered(self):
        assert set(VAT_TREATMENTS) == {'inclusive', 'exclusive', 'zero_rated',
                                       'exempt', 'non_vat'}

    def test_the_form_offers_them_with_the_owners_labels(self):
        from app.purchase_orders.forms import PurchaseOrderForm
        labels = dict(PurchaseOrderForm.vat_treatment.kwargs['choices'])
        assert labels['exempt'] == 'VAT Exempt'
        assert labels['non_vat'] == 'Non-VAT'
        # Control: the three that already existed keep their labels.
        assert labels['inclusive'] == 'VAT Inclusive'
        assert labels['zero_rated'] == 'Zero-Rated'


class TestThePrintedOrder:
    """A second surface, and the one a VENDOR reads.

    vat_treatment_label falls back to the raw token when a value is missing from
    VAT_TREATMENT_LABELS, so adding the dropdown options alone would have sent
    an order out reading "non_vat".
    """

    def test_every_treatment_has_a_printed_label(self, db_session):
        from app.purchase_orders.models import (VAT_TREATMENTS,
                                                VAT_TREATMENT_LABELS)
        missing = [t for t in VAT_TREATMENTS if t not in VAT_TREATMENT_LABELS]
        assert not missing, (
            'these would print as their raw token on the vendor copy: %s'
            % missing)

    def test_the_new_ones_print_in_words(self, db_session):
        po = _po('exempt')
        assert po.vat_treatment_label == 'VAT Exempt'
        po = _po('non_vat')
        assert po.vat_treatment_label == 'Non-VAT'

    def test_an_unknown_token_still_shows_itself(self, db_session):
        """CONTROL: the fallback stays, so a bad value is visible on the page
        rather than printing blank."""
        po = _po('mystery')
        assert po.vat_treatment_label == 'mystery'
