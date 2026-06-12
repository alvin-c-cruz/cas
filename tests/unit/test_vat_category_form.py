"""VATCategoryForm: input_vat_account_id required when rate > 0 (B-014)."""
from app.vat_categories.forms import VATCategoryForm


def make_form(app, rate, account_id):
    with app.test_request_context(method='POST', data={
        'code': 'VX', 'name': 'X', 'rate': str(rate),
        'is_active': '1', 'request_reason': 'test reason',
        'input_vat_account_id': str(account_id) if account_id is not None else '0',
    }):
        form = VATCategoryForm(meta={'csrf': False})
        # choices are populated by the view; emulate
        form.input_vat_account_id.choices = [(0, '-- None --'), (5, '10502 : Input VAT - Domestic Goods')]
        return form, form.validate()


class TestRateConditionalAccount:
    def test_rate_positive_without_account_rejected(self, app):
        form, ok = make_form(app, 12, None)
        assert ok is False
        assert any('Input Tax account' in e for e in form.input_vat_account_id.errors)

    def test_rate_positive_with_account_ok(self, app):
        form, ok = make_form(app, 12, 5)
        assert ok is True

    def test_rate_zero_without_account_ok(self, app):
        form, ok = make_form(app, 0, None)
        assert ok is True
