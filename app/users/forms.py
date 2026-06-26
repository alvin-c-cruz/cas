from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SelectMultipleField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, Optional
from app.users.models import User
from app.users.validators import PasswordPolicy


class LoginForm(FlaskForm):
    """User login form."""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')


class RegistrationForm(FlaskForm):
    """User registration form."""
    username = StringField('Username', validators=[
        DataRequired(),
        Length(min=3, max=80, message='Username must be between 3 and 80 characters.')
    ])
    email = StringField('Email', validators=[
        DataRequired(),
        Email(message='Please enter a valid email address.')
    ])
    full_name = StringField('Full Name', validators=[
        DataRequired(),
        Length(min=2, max=200, message='Full name must be between 2 and 200 characters.')
    ])
    password = PasswordField('Password', validators=[
        DataRequired(),
        PasswordPolicy(min_length=12)
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match.')
    ])

    def validate_username(self, username):
        """Check if username already exists."""
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already exists. Please choose a different one.')

    def validate_email(self, email):
        """Check if email already exists and if it's pre-approved."""
        # Check if email is already registered
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered. Please use a different one.')

        # Check if email is pre-approved for registration
        from app.users.approved_emails import ApprovedEmail
        if not ApprovedEmail.is_email_approved(email.data):
            raise ValidationError('This email is not pre-approved for registration. Please contact the administrator to add your email to the approved list.')


class UserForm(FlaskForm):
    """User management form (create/edit)."""
    username = StringField('Username', validators=[
        DataRequired(),
        Length(min=3, max=80, message='Username must be between 3 and 80 characters.')
    ])
    email = StringField('Email', validators=[
        DataRequired(),
        Email(message='Please enter a valid email address.')
    ])
    full_name = StringField('Full Name', validators=[
        DataRequired(),
        Length(min=2, max=200, message='Full name must be between 2 and 200 characters.')
    ])
    role = SelectField('Role', choices=[
        ('viewer', 'Viewer'),
        ('staff', 'Staff'),
        ('accountant', 'Accountant'),
        ('admin', 'Administrator')
    ], validators=[DataRequired()])
    branch_ids = SelectMultipleField('Branch Assignments', coerce=int)
    is_active = BooleanField('Active')

    def validate_branch_ids(self, field):
        if self.role.data != 'admin' and not field.data:
            raise ValidationError('Assign at least one branch for non-admin roles.')
    password = PasswordField('Password', validators=[
        Optional(),
        PasswordPolicy(min_length=12)
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        Optional(),
        EqualTo('password', message='Passwords must match.')
    ])


class ChangePasswordForm(FlaskForm):
    """Change password form."""
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[
        DataRequired(),
        PasswordPolicy(min_length=12)
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('new_password', message='Passwords must match.')
    ])


class RejectReasonForm(FlaskForm):
    """CSRF-protected form for capturing a reject reason (no other fields needed)."""
    reason = TextAreaField('Reason', validators=[Optional(), Length(max=500)])


class ApprovedEmailForm(FlaskForm):
    """Form for adding pre-approved email addresses for registration."""
    email = StringField('Email Address', validators=[
        DataRequired(),
        Email(message='Please enter a valid email address.')
    ])
    notes = TextAreaField('Notes (Optional)', validators=[
        Optional(),
        Length(max=500, message='Notes must not exceed 500 characters.')
    ])

    def validate_email(self, email):
        """Check if email is already in approved list."""
        from app.users.approved_emails import ApprovedEmail
        approved = ApprovedEmail.query.filter_by(email=email.data.lower()).first()
        if approved:
            if approved.is_used:
                raise ValidationError(f'This email has already been used for registration by {approved.used_by.username}.')
            else:
                raise ValidationError('This email is already in the approved list.')
