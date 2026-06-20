from app.sales_vat_categories.forms import SalesVATCategoryForm


def test_output_account_required_when_rated(app):
    with app.test_request_context():
        form = SalesVATCategoryForm(meta={'csrf': False}, formdata=None)
        form.output_vat_account_id.choices = [(0, '--'), (5, '2100')]
        form.process(data={'code': 'SVAT-G', 'name': 'Goods', 'rate': '12.00',
                            'transaction_nature': 'regular', 'output_vat_account_id': 0,
                            'is_active': '1'})
        assert not form.validate()
        assert 'output_vat_account_id' in form.errors


def test_output_account_optional_when_zero(app):
    with app.test_request_context():
        form = SalesVATCategoryForm(meta={'csrf': False})
        form.output_vat_account_id.choices = [(0, '--'), (5, '2100')]
        form.process(data={'code': 'SVAT-EX', 'name': 'Exempt', 'rate': '0.00',
                            'transaction_nature': 'exempt', 'output_vat_account_id': 0,
                            'is_active': '1'})
        assert form.validate(), form.errors
