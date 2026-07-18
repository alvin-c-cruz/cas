import pytest
from app.products.forms import ProductForm


def _base_data(**overrides):
    data = {'code': 'F-1', 'name': 'Form Widget', 'description': '',
            'default_unit_of_measure_id': '', 'default_unit_price': '',
            'default_account_id': '', 'category_id': '', 'is_active': '1'}
    data.update(overrides)
    return data


def _form(**overrides):
    """Build a ProductForm with the dynamic FK-select choices populated (normally
    done by products/views.py::_populate_choices at request time) so pre_validate
    on those unrelated SelectFields doesn't reject a raw unit-level form build."""
    form = ProductForm(meta={'csrf': False})
    form.default_unit_of_measure_id.choices = [('', '— None —')]
    form.default_account_id.choices = [('', '— None —')]
    form.category_id.choices = [('', '— None —')]
    return form


def test_track_inventory_unchecked_allows_blank_costing_fields(app):
    with app.test_request_context(method='POST', data=_base_data()):
        form = _form()
        assert form.validate() is True


def test_track_inventory_checked_requires_costing_method_and_cost(app):
    with app.test_request_context(method='POST', data=_base_data(track_inventory='y')):
        form = _form()
        assert form.validate() is False
        assert form.track_inventory.errors


def test_track_inventory_checked_with_costing_method_and_cost_passes(app):
    with app.test_request_context(method='POST', data=_base_data(
            track_inventory='y', costing_method='moving_average', standard_cost='150.00')):
        form = _form()
        assert form.validate() is True


def test_costing_method_rejects_unknown_value(app):
    with app.test_request_context(method='POST', data=_base_data(
            track_inventory='y', costing_method='bogus_method', standard_cost='150.00')):
        form = _form()
        assert form.validate() is False
