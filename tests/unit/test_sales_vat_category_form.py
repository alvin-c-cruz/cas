from werkzeug.datastructures import MultiDict
from app.sales_vat_categories.forms import SalesVATCategoryForm


def test_output_account_required_when_rated(app):
    with app.test_request_context():
        form = SalesVATCategoryForm(
            formdata=MultiDict({'code': 'SVAT-G', 'name': 'Goods', 'rate': '12.00',
                                'transaction_nature': 'regular',
                                'output_vat_account_id': '0', 'is_active': '1'}),
            meta={'csrf': False})
        form.output_vat_account_id.choices = [(0, '--'), (5, '2100')]
        assert not form.validate()
        assert 'output_vat_account_id' in form.errors


def test_output_account_optional_when_zero(app):
    with app.test_request_context():
        form = SalesVATCategoryForm(
            formdata=MultiDict({'code': 'SVAT-EX', 'name': 'Exempt', 'rate': '0.00',
                                'transaction_nature': 'exempt',
                                'output_vat_account_id': '0', 'is_active': '1'}),
            meta={'csrf': False})
        form.output_vat_account_id.choices = [(0, '--'), (5, '2100')]
        assert form.validate(), form.errors


def test_zero_rate_via_formdata_accepted(app):
    """Regression guard: rate=0.00 submitted as formdata must not be rejected.

    The bug: DataRequired rejects Decimal('0.00') because bool(Decimal('0.00')) is False.
    This test drives the form through the production path (formdata=MultiDict) so
    DecimalField coerces the string to Decimal exactly as in a real HTTP request.
    """
    with app.test_request_context():
        form = SalesVATCategoryForm(
            formdata=MultiDict({'code': 'SVAT-EX', 'name': 'Exempt', 'rate': '0.00',
                                'transaction_nature': 'exempt',
                                'output_vat_account_id': '0', 'is_active': '1'}),
            meta={'csrf': False})
        form.output_vat_account_id.choices = [(0, '--'), (5, '2100')]
        assert form.validate(), form.errors
