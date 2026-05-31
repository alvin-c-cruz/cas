from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Length, Optional

class AccountForm(FlaskForm):
    """Form for creating and editing accounts"""

    code = StringField('Account Code',
                      validators=[DataRequired(), Length(min=1, max=20)],
                      render_kw={'placeholder': 'e.g., 1000'})

    name = StringField('Account Name',
                      validators=[DataRequired(), Length(min=1, max=200)],
                      render_kw={'placeholder': 'e.g., Cash'})

    account_type = SelectField('Account Type',
                              validators=[DataRequired()],
                              choices=[
                                  ('', 'Select Type'),
                                  ('Asset', 'Asset'),
                                  ('Liability', 'Liability'),
                                  ('Equity', 'Equity'),
                                  ('Revenue', 'Revenue'),
                                  ('Expense', 'Expense')
                              ])

    classification = SelectField('Classification',
                                validators=[Optional()],
                                choices=[
                                    ('', 'None'),
                                    ('Current', 'Current'),
                                    ('Non-Current', 'Non-Current')
                                ])

    normal_balance = SelectField('Normal Balance',
                                validators=[DataRequired()],
                                choices=[
                                    ('', 'Select'),
                                    ('Debit', 'Debit'),
                                    ('Credit', 'Credit')
                                ])

    parent_id = SelectField('Parent Account',
                           validators=[Optional()],
                           coerce=lambda x: int(x) if x else None,
                           choices=[('', 'None (Top Level)')])

    description = TextAreaField('Description',
                               validators=[Optional()],
                               render_kw={'placeholder': 'Optional description of this account', 'rows': 3})

    def populate_parent_choices(self, accounts, exclude_id=None):
        """Populate parent account choices dynamically"""
        choices = [('', 'None (Top Level)')]
        for account in accounts:
            if exclude_id is None or account.id != exclude_id:
                choices.append((str(account.id), f'{account.code} - {account.name}'))
        self.parent_id.choices = choices
