"""Pre-printed voucher forms — designer forms (P-69).

The designer page (Task 5) posts raw JSON strings (fields_json/line_band_json)
and file uploads directly via plain HTML forms; there is no field-by-field
WTForms validation to do here. This minimal FlaskForm exists only so designer
templates can render `{{ form.hidden_tag() }}` / `{{ csrf_token() }}` the same
way every other CAS form does.
"""
from flask_wtf import FlaskForm


class PreprintedFormCSRFForm(FlaskForm):
    """CSRF-only form for the designer/admin stub templates."""
    pass
