from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Length, Optional
from app.accounts.account_types import ACCOUNT_TYPES, CLASSIFICATIONS

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
                              choices=[('', 'Select Type')] + [(t, t) for t in ACCOUNT_TYPES])

    classification = SelectField('Classification',
                                validators=[Optional()],
                                choices=[('', '—')] + [(c, c) for c in CLASSIFICATIONS])

    normal_balance = SelectField('Normal Balance',
                                validators=[Optional()],
                                choices=[
                                    ('', 'Select'),
                                    ('debit', 'Debit'),
                                    ('credit', 'Credit')
                                ])

    parent_id = SelectField('Parent Account',
                           validators=[Optional()],
                           coerce=lambda x: int(x) if x else None,
                           choices=[('', 'None (Top Level)')])

    description = TextAreaField('Description',
                               validators=[Optional()],
                               render_kw={'placeholder': 'Optional description of this account', 'rows': 3})

    request_reason = TextAreaField('Reason for Change',
                                  validators=[
                                      Optional(),
                                      Length(max=500, message='Reason must be 500 characters or less')
                                  ],
                                  render_kw={'placeholder': 'Why is this change needed?', 'rows': 3})

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        if require_reason:
            self.request_reason.validators = [
                DataRequired(message='Please explain why this change is needed'),
                Length(max=500, message='Reason must be 500 characters or less')
            ]

    def populate_parent_choices(self, accounts, exclude_id=None):
        """Populate parent account choices dynamically"""
        choices = [('', 'None (Top Level)')]
        for account in accounts:
            if exclude_id is None or account.id != exclude_id:
                choices.append((str(account.id), f'{account.code} - {account.name}'))
        self.parent_id.choices = choices
