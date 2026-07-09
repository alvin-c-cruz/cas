import pytest
from app.vat_categories.models import (
    VATCategory, PURCHASE_NATURES, PURCHASE_NATURE_BY_CODE,
)


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
