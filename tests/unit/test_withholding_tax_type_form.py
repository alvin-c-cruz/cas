from werkzeug.datastructures import MultiDict
from app.withholding_tax.models import WithholdingTax, TAX_TYPES
from app.withholding_tax.forms import WithholdingTaxForm


class TestTaxTypeColumn:
    def test_tax_types_defined(self):
        assert TAX_TYPES == ('expanded', 'final')

    def test_defaults_to_expanded(self, db_session):
        wt = WithholdingTax(code='WX1', name='Probe', rate=2.00, is_active=True)
        db_session.add(wt)
        db_session.commit()
        assert wt.tax_type == 'expanded'

    def test_final_round_trips(self, db_session):
        wt = WithholdingTax(code='WX2', name='Bank Interest', rate=20.00,
                            is_active=True, tax_type='final')
        db_session.add(wt)
        db_session.commit()
        assert db_session.get(WithholdingTax, wt.id).tax_type == 'final'

    def test_to_dict_exposes_tax_type(self, db_session):
        wt = WithholdingTax(code='WX3', name='Probe', rate=5.00, is_active=True)
        db_session.add(wt)
        db_session.commit()
        assert wt.to_dict()['tax_type'] == 'expanded'


class TestWithholdingTaxFormTaxType:
    def _formdata(self, **overrides):
        base = {'code': 'WC010', 'name': 'Professional Fees', 'rate': '10.00',
                'tax_type': 'expanded', 'is_active': '1'}
        base.update(overrides)
        return MultiDict(base)

    def test_expanded_accepted(self, app):
        with app.test_request_context():
            form = WithholdingTaxForm(formdata=self._formdata(), meta={'csrf': False})
            assert form.validate(), form.errors
            assert form.tax_type.data == 'expanded'

    def test_final_accepted(self, app):
        with app.test_request_context():
            form = WithholdingTaxForm(formdata=self._formdata(tax_type='final'),
                                      meta={'csrf': False})
            assert form.validate(), form.errors

    def test_bogus_type_rejected(self, app):
        with app.test_request_context():
            form = WithholdingTaxForm(formdata=self._formdata(tax_type='creditable'),
                                      meta={'csrf': False})
            assert not form.validate()
            assert 'tax_type' in form.errors
