"""WTForms form definitions for the Product master."""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DecimalField
from wtforms.validators import DataRequired, Length, Optional, NumberRange


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
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])
