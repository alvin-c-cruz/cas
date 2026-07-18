"""Integration test: fixed_assets/form.html readonly/disabled context-flag defaults.

Review finding (R-05): form.html is a SHARED template reused by three later
tasks (opening-asset flow, tag flow, edit flow), each rendering it with a
different combination of the is_opening / readonly_acquisition /
readonly_code context flags. The template guards each flag at its top with:

    {% set readonly_code = readonly_code|default(false) %}
    {% set readonly_acquisition = readonly_acquisition|default(false) %}
    {% set is_opening = is_opening|default(false) %}

This exists to fix a real bug: WTForms' html_params() only OMITS the
readonly/disabled HTML attribute when the Python value is the literal
False -- a Jinja Undefined (what a caller gets by omitting one of these
kwargs from render_template()) stringifies to "", and html_params() treats
any truthy/non-False value as "attribute present". Without the
|default(false) guard, every field would silently render readonly/disabled
the instant a future task's view forgot to pass one of these flags.

This was previously verified only via an uncommitted, throwaway script.
These tests make the guard durable: removing the three `{% set %}` lines
turns test_flags_omitted_render_writable RED (see the commit message / task
report for the RED/GREEN proof).
"""
import re

import pytest
from flask import render_template

from app.fixed_assets.forms import FixedAssetForm

pytestmark = [pytest.mark.integration]


def _populate_choices(form):
    """branch_id/category_id/*_account_id are populated dynamically by the
    view in real usage; give them one choice each so the SelectField/Jinja
    render doesn't choke on an empty options list."""
    form.branch_id.choices = [(1, 'Main Branch')]
    form.category_id.choices = [('', '-- None --')]
    form.accumulated_depreciation_account_id.choices = [(1, 'Accumulated Depreciation')]
    form.depreciation_expense_account_id.choices = [(1, 'Depreciation Expense')]
    form.cost_account_id.choices = [(1, 'Equipment Cost')]
    return form


def _ensure_list_endpoint(app):
    """form.html's Cancel link calls url_for('fixed_assets.list'), which is
    only wired up by a later task (opening/tag/edit views, not yet built on
    this branch). Stub the endpoint so this render-only test of form.html's
    own logic doesn't depend on a route from a different, not-yet-implemented
    task."""
    if 'fixed_assets.list' not in app.view_functions:
        app.add_url_rule('/fixed-assets', endpoint='fixed_assets.list', view_func=lambda: '')


def _render(app, **context):
    _ensure_list_endpoint(app)
    with app.test_request_context():
        form = _populate_choices(FixedAssetForm(meta={'csrf': False}))
        return render_template('fixed_assets/form.html', form=form, title='Test',
                                asset=None, **context)


def _tag(html, field_id):
    """Pull the single <input .../> or <select ...>...</select> opening tag
    for a field id, so assertions are scoped to that field -- base.html's
    inline <style> block itself contains the literal strings "readonly" and
    "disabled" (CSS selectors), so a whole-document substring check would be
    a false positive regardless of the flags under test."""
    match = re.search(rf'<(?:input|select)[^>]*\bid="{field_id}"[^>]*?>', html)
    assert match, f'field id="{field_id}" not found in rendered HTML'
    return match.group(0)


class TestFormReadonlyFlagDefaults:
    """Guards the |default(false) coercions at the top of form.html."""

    def test_flags_omitted_render_writable(self, app, db_session):
        """No is_opening/readonly_acquisition/readonly_code kwargs passed at
        all (the scenario every future caller risks hitting by omission) --
        the guard must keep every field writable and hide the opening field."""
        html = _render(app)

        assert 'readonly' not in _tag(html, 'code')
        assert 'readonly' not in _tag(html, 'acquisition_cost')
        assert 'disabled' not in _tag(html, 'cost_account_id')
        # A disabled select needs a hidden re-send input (disabled selects
        # don't POST); with the select enabled, that hidden input must be
        # absent.
        assert '<input type="hidden" name="cost_account_id"' not in html
        assert 'opening_accumulated_depreciation' not in html

    def test_flags_explicit_render_locked_and_shows_opening(self, app, db_session):
        """is_opening/readonly_acquisition/readonly_code all explicitly True
        -- the opposite scenario: fields must be locked and the opening
        field must appear, with a hidden re-send input backing the disabled
        cost_account_id select."""
        html = _render(app, is_opening=True, readonly_acquisition=True,
                        readonly_code=True)

        assert 'readonly' in _tag(html, 'code')
        assert 'readonly' in _tag(html, 'acquisition_cost')
        assert 'disabled' in _tag(html, 'cost_account_id')
        assert '<input type="hidden" name="cost_account_id"' in html
        assert 'id="opening_accumulated_depreciation"' in html
