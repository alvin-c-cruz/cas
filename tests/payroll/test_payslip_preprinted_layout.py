"""Sanitizer round-trip test for the payslip preprinted layout (mirrors
tests/{sales_invoices}/test_preprinted_layout.py's shape -- check that sibling
file for its exact test structure before writing this, since the sanitizer's
public function names/signatures must match app/payroll/preprinted_layout.py
exactly once Step 2 below defines them)."""
from app.payroll.preprinted_layout import (
    get_layout, save_layout, DEFAULT_PAYSLIP_PREPRINTED_LAYOUT, FIELD_KEYS,
)


def test_default_layout_has_every_field_key(app_ctx, main_branch):
    layout = get_layout(main_branch.id)
    for key in FIELD_KEYS:
        assert key in layout['fields'], f'{key} missing from default layout'


def test_save_and_reload_round_trips(app_ctx, main_branch):
    layout = get_layout(main_branch.id)
    layout['fields']['employee_name']['x'] = 100
    save_layout(main_branch.id, layout, updated_by='test')

    reloaded = get_layout(main_branch.id)
    assert reloaded['fields']['employee_name']['x'] == 100


def test_save_rejects_unknown_field_key(app_ctx, main_branch):
    layout = get_layout(main_branch.id)
    layout['fields']['not_a_real_field'] = {'x': 0, 'y': 0, 'fontSize': 10, 'bold': False}
    save_layout(main_branch.id, layout, updated_by='test')

    reloaded = get_layout(main_branch.id)
    assert 'not_a_real_field' not in reloaded['fields'], \
        'the sanitizer must strip unknown keys on write, mirroring the SI layout sanitizer'


def test_save_clamps_out_of_range_font_size(app_ctx, main_branch):
    layout = get_layout(main_branch.id)
    layout['fields']['employee_name']['fontSize'] = 999
    save_layout(main_branch.id, layout, updated_by='test')

    reloaded = get_layout(main_branch.id)
    from app.payroll.preprinted_layout import FONT_MAX
    assert reloaded['fields']['employee_name']['fontSize'] <= FONT_MAX
