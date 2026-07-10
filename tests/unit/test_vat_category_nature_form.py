import pytest
from werkzeug.datastructures import MultiDict
from app.vat_categories.models import (
    VATCategory, PURCHASE_NATURES, PURCHASE_NATURE_BY_CODE,
    PURCHASE_NATURE_LABELS, format_purchase_nature,
)
from app.vat_categories.forms import VATCategoryForm


class TestPurchaseNatures:
    def test_eight_natures_defined(self):
        assert PURCHASE_NATURES == (
            'capital_goods', 'domestic_goods', 'domestic_services',
            'importation', 'nonresident_services', 'exempt',
            'zero_rated', 'not_qualified',
        )

    def test_standard_seed_codes_map(self):
        assert PURCHASE_NATURE_BY_CODE['V12CG'] == 'capital_goods'
        assert PURCHASE_NATURE_BY_CODE['V12DG'] == 'domestic_goods'
        assert PURCHASE_NATURE_BY_CODE['V12SV'] == 'domestic_services'
        assert PURCHASE_NATURE_BY_CODE['V12IM'] == 'importation'
        assert PURCHASE_NATURE_BY_CODE['VEX'] == 'exempt'
        assert PURCHASE_NATURE_BY_CODE['V0'] == 'zero_rated'
        assert PURCHASE_NATURE_BY_CODE['INV'] == 'not_qualified'

    def test_legacy_seed_codes_map(self):
        assert PURCHASE_NATURE_BY_CODE['VATABLE'] == 'domestic_goods'
        assert PURCHASE_NATURE_BY_CODE['VAT-EXEMPT'] == 'exempt'
        assert PURCHASE_NATURE_BY_CODE['ZERO-RATED'] == 'zero_rated'
        assert PURCHASE_NATURE_BY_CODE['NON-VAT'] == 'not_qualified'

    def test_unknown_code_has_no_mapping(self):
        assert PURCHASE_NATURE_BY_CODE.get('CLIENT-CUSTOM') is None

    def test_nonresident_services_is_selectable_but_unseeded(self):
        assert 'nonresident_services' in PURCHASE_NATURES
        assert 'nonresident_services' not in PURCHASE_NATURE_BY_CODE.values()

    def test_labels_have_exactly_one_entry_per_nature(self):
        """PURCHASE_NATURE_LABELS must never drift from PURCHASE_NATURES --
        exactly one label per defined nature, no more, no fewer."""
        assert set(PURCHASE_NATURE_LABELS.keys()) == set(PURCHASE_NATURES)
        assert len(PURCHASE_NATURE_LABELS) == len(PURCHASE_NATURES)


class TestFormatPurchaseNature:
    """The '-' fallback used to conflate None (legitimately unclassified)
    with a present-but-unrecognized token (a data-integrity signal). The two
    must render distinguishably."""

    def test_none_renders_unclassified(self):
        assert format_purchase_nature(None) == '(unclassified)'

    def test_recognized_value_renders_its_label(self):
        assert format_purchase_nature('capital_goods') == PURCHASE_NATURE_LABELS['capital_goods']

    def test_unrecognized_value_renders_distinctly_from_unclassified(self):
        result = format_purchase_nature('some_stale_token')
        assert result != '(unclassified)'
        assert 'some_stale_token' in result


class TestVATCategoryNatureColumn:
    def test_nature_defaults_to_none(self, db_session):
        cat = VATCategory(code='X1', name='Test', rate=12.00, is_active=True)
        db_session.add(cat)
        db_session.commit()
        assert cat.transaction_nature is None

    def test_nature_round_trips(self, db_session):
        cat = VATCategory(code='X2', name='Test', rate=12.00, is_active=True,
                          transaction_nature='capital_goods')
        db_session.add(cat)
        db_session.commit()
        assert db_session.get(VATCategory, cat.id).transaction_nature == 'capital_goods'

    def test_to_dict_exposes_nature(self, db_session):
        cat = VATCategory(code='X3', name='Test', rate=0.00, is_active=True,
                          transaction_nature='exempt')
        db_session.add(cat)
        db_session.commit()
        assert cat.to_dict()['transaction_nature'] == 'exempt'


class TestVATCategoryFormNature:
    """WTForms validation tests MUST feed formdata=MultiDict, never data=.
    Passing data= skips coercion, so validator bugs pass silently."""

    def _formdata(self, **overrides):
        base = {
            'code': 'V12DG', 'name': 'Input Tax Domestic Goods',
            'rate': '12.00', 'input_vat_account_id': '1',
            'transaction_nature': 'domestic_goods', 'is_active': '1',
        }
        base.update(overrides)
        return MultiDict(base)

    def test_valid_nature_accepted(self, app):
        with app.test_request_context():
            form = VATCategoryForm(formdata=self._formdata(), meta={'csrf': False})
            form.input_vat_account_id.choices = [(1, 'Input VAT')]
            assert form.validate(), form.errors
            assert form.transaction_nature.data == 'domestic_goods'

    def test_missing_nature_rejected(self, app):
        with app.test_request_context():
            form = VATCategoryForm(formdata=self._formdata(transaction_nature=''),
                                   meta={'csrf': False})
            form.input_vat_account_id.choices = [(1, 'Input VAT')]
            assert not form.validate()
            assert 'transaction_nature' in form.errors

    def test_bogus_nature_rejected(self, app):
        with app.test_request_context():
            form = VATCategoryForm(formdata=self._formdata(transaction_nature='banana'),
                                   meta={'csrf': False})
            form.input_vat_account_id.choices = [(1, 'Input VAT')]
            assert not form.validate()
            assert 'transaction_nature' in form.errors
