from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, Optional
from app.users.models import User


class LoginForm(FlaskForm):
    """User login form."""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField('Password', validators=[DataRequired()])
    branch = SelectField('Branch', coerce=int, validators=[DataRequired()])
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
        Length(min=6, message='Password must be at least 6 characters.')
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
        """Check if email already exists."""
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered. Please use a different one.')


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
    is_active = BooleanField('Active')
    password = PasswordField('Password', validators=[
        Optional(),
        Length(min=6, message='Password must be at least 6 characters.')
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
        Length(min=6, message='Password must be at least 6 characters.')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('new_password', message='Passwords must match.')
    ])
