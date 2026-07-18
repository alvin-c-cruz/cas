"""WTForms form definitions for the Product master."""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DecimalField, BooleanField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, ValidationError
from app.products.models import COSTING_METHODS

_COSTING_METHOD_CHOICES = [('', '— None —')] + [(m, m.replace('_', ' ').title())
                                                 for m in COSTING_METHODS]


class ProductForm(FlaskForm):
    code = StringField('Code', validators=[DataRequired(message='Code is required.'),
                                           Length(max=50)])
    name = StringField('Name', validators=[DataRequired(message='Name is required.'),
                                           Length(max=200)])
    description = TextAreaField('Description', validators=[Optional()])
    job_order_name = StringField('Job Order Name', validators=[Optional(), Length(max=200)])
    # choices populated in the view from active UOMs / accounts; '' = none
    default_unit_of_measure_id = SelectField('Default Unit of Measure',
                                             validators=[Optional()], default='')
    default_unit_price = DecimalField('Default Unit Price (₱, VAT-inclusive)', places=2,
                                      validators=[Optional(), NumberRange(min=0)])
    default_account_id = SelectField('Default Account', validators=[Optional()], default='')
    category_id = SelectField('Category', validators=[Optional()], default='')
    track_inventory = BooleanField('Track Inventory')
    costing_method = SelectField('Costing Method', choices=_COSTING_METHOD_CHOICES,
                                 validators=[Optional()], default='')
    standard_cost = DecimalField('Standard Cost (₱)', places=2,
                                 validators=[Optional(), NumberRange(min=0)])
    reorder_level = DecimalField('Reorder Level (Qty)', places=2,
                                 validators=[Optional(), NumberRange(min=0)])
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])

    def validate_track_inventory(self, field):
        """When inventory tracking is on, a costing method + cost basis are required.
        When off, the other three fields are left alone -- no validation error, and no
        value is cleared (a product can be un-tracked while keeping stale prior values)."""
        if not field.data:
            return
        missing = []
        if not self.costing_method.data:
            missing.append('a costing method')
        if self.standard_cost.data is None:
            missing.append('a standard cost')
        if missing:
            raise ValidationError(
                f"{' and '.join(missing).capitalize()} required when Track Inventory is checked.")
