from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, IntegerField, DateField, DecimalField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, ValidationError
from app.fixed_assets.models import DEPRECIATION_METHODS

_METHOD_CHOICES = [('', '-- None --')] + [(m, m.replace('_', ' ').title())
                                           for m in DEPRECIATION_METHODS]


class AssetCategoryForm(FlaskForm):
    name = StringField('Name', validators=[
        DataRequired(message='Name is required.'),
        Length(max=100, message='Name must be 100 characters or less.')])
    default_useful_life_months = IntegerField('Default Useful Life (months)', validators=[
        Optional(), NumberRange(min=1, message='Must be at least 1 month.')])
    default_depreciation_method = SelectField('Default Depreciation Method',
                                               choices=_METHOD_CHOICES,
                                               validators=[Optional()])
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])


class FixedAssetForm(FlaskForm):
    code = StringField('Asset Code', validators=[
        DataRequired(message='Asset code is required.'),
        Length(max=20, message='Asset code must be 20 characters or less.')])
    name = StringField('Name', validators=[
        DataRequired(message='Name is required.'),
        Length(max=200, message='Name must be 200 characters or less.')])
    # branch_id/category_id/*_account_id choices are populated dynamically by the
    # view (branches, active categories, leaf accounts via leaf_accounts_by_type);
    # validate_choice off so a valid but not-yet-repopulated id (e.g. re-render
    # after a validation error) isn't rejected -- mirrors the codebase convention
    # for dynamically-populated FK selects (see purchase_orders/forms.py etc.).
    branch_id = SelectField('Branch', coerce=int, validate_choice=False, validators=[
        DataRequired(message='Branch is required.')])
    category_id = SelectField('Category', validate_choice=False, validators=[Optional()])

    accumulated_depreciation_account_id = SelectField(
        'Accumulated Depreciation Account', coerce=int, validate_choice=False,
        validators=[DataRequired(message='Accumulated depreciation account is required.')])
    depreciation_expense_account_id = SelectField(
        'Depreciation Expense Account', coerce=int, validate_choice=False,
        validators=[DataRequired(message='Depreciation expense account is required.')])

    depreciation_method = SelectField('Depreciation Method',
                                      choices=[(m, m.replace('_', ' ').title())
                                               for m in DEPRECIATION_METHODS],
                                      validators=[DataRequired()])
    useful_life_months = IntegerField('Useful Life (months)', validators=[
        Optional(), NumberRange(min=1, message='Must be at least 1 month.')])
    declining_balance_rate = DecimalField('Declining Balance Rate (%)', validators=[
        Optional(), NumberRange(min=0, message='Must be zero or more.')])
    total_estimated_units = DecimalField('Total Estimated Units', validators=[
        Optional(), NumberRange(min=0, message='Must be zero or more.')])
    salvage_value = DecimalField('Salvage Value', validators=[Optional()], default=0)

    acquisition_date = DateField('Acquisition Date', validators=[
        DataRequired(message='Acquisition date is required.')])
    acquisition_cost = DecimalField('Acquisition Cost', validators=[
        DataRequired(message='Acquisition cost is required.'),
        NumberRange(min=0.01, message='Must be greater than zero.')])
    cost_account_id = SelectField('Cost Account', coerce=int, validate_choice=False, validators=[
        DataRequired(message='Cost account is required.')])

    opening_accumulated_depreciation = DecimalField(
        'Opening Accumulated Depreciation', validators=[Optional()], default=0)

    def validate_depreciation_method(self, field):
        """Cross-field: each method needs its own driving figure."""
        if field.data == 'straight_line' and not self.useful_life_months.data:
            raise ValidationError('Straight-line requires a useful life in months.')
        if field.data == 'declining_balance':
            if not self.useful_life_months.data:
                raise ValidationError('Declining-balance requires a useful life in months.')
            if not self.declining_balance_rate.data:
                raise ValidationError('Declining-balance requires a rate.')
        if field.data == 'units_of_production' and not self.total_estimated_units.data:
            raise ValidationError('Units-of-production requires total estimated units.')
