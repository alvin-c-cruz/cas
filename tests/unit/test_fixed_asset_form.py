from app import create_app
from app.fixed_assets.forms import FixedAssetForm


def _form(app, **overrides):
    data = {
        'code': 'FA-0001', 'name': 'Laptop', 'branch_id': '1', 'category_id': '',
        'accumulated_depreciation_account_id': '2', 'depreciation_expense_account_id': '3',
        'depreciation_method': 'straight_line', 'useful_life_months': '36',
        'declining_balance_rate': '', 'total_estimated_units': '',
        'salvage_value': '0', 'acquisition_date': '2026-01-15',
        'acquisition_cost': '50000.00', 'cost_account_id': '1',
        'opening_accumulated_depreciation': '0',
    }
    data.update(overrides)
    with app.test_request_context(method='POST', data=data):
        form = FixedAssetForm(meta={'csrf': False})
        return form


def test_straight_line_requires_useful_life(app):
    form = _form(app, useful_life_months='')
    assert not form.validate()
    assert 'useful_life_months' in str(form.errors).lower() or form.errors


def test_declining_balance_requires_rate(app):
    form = _form(app, depreciation_method='declining_balance', useful_life_months='',
                declining_balance_rate='')
    assert not form.validate()


def test_units_of_production_requires_total_units(app):
    form = _form(app, depreciation_method='units_of_production', useful_life_months='',
                total_estimated_units='')
    assert not form.validate()


def test_valid_straight_line_form(app):
    form = _form(app)
    assert form.validate(), form.errors
