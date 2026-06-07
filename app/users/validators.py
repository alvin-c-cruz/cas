"""
Password policy validators for CAS application.

Implements strong password requirements:
- Minimum 12 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one number
- At least one special character
- Cannot contain username
- Not a common/weak password
"""

from wtforms.validators import ValidationError
import re


class PasswordPolicy:
    """
    WTForms validator for enforcing strong password policies.

    Usage:
        password = PasswordField('Password', validators=[
            DataRequired(),
            PasswordPolicy()
        ])
    """

    def __init__(self,
                 min_length=12,
                 require_uppercase=True,
                 require_lowercase=True,
                 require_number=True,
                 require_special=True,
                 check_common_passwords=True):
        """
        Initialize password policy validator.

        Args:
            min_length: Minimum password length (default: 12)
            require_uppercase: Require at least one uppercase letter (default: True)
            require_lowercase: Require at least one lowercase letter (default: True)
            require_number: Require at least one number (default: True)
            require_special: Require at least one special character (default: True)
            check_common_passwords: Check against common password list (default: True)
        """
        self.min_length = min_length
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase
        self.require_number = require_number
        self.require_special = require_special
        self.check_common_passwords = check_common_passwords

    def __call__(self, form, field):
        """Validate password against policy."""
        password = field.data

        if not password:
            return  # Let DataRequired handle empty passwords

        errors = []

        # Check minimum length
        if len(password) < self.min_length:
            errors.append(f'Password must be at least {self.min_length} characters long')

        # Check for uppercase letter
        if self.require_uppercase and not re.search(r'[A-Z]', password):
            errors.append('Password must contain at least one uppercase letter')

        # Check for lowercase letter
        if self.require_lowercase and not re.search(r'[a-z]', password):
            errors.append('Password must contain at least one lowercase letter')

        # Check for number
        if self.require_number and not re.search(r'\d', password):
            errors.append('Password must contain at least one number')

        # Check for special character
        if self.require_special and not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\',.<>?/\\|`~]', password):
            errors.append('Password must contain at least one special character (!@#$%^&*()_+-=[]{};\':,.<>?/\\|`~)')

        # Check if password contains username (if username field exists)
        if hasattr(form, 'username') and form.username.data:
            username = form.username.data.lower()
            if username in password.lower():
                errors.append('Password cannot contain your username')

        # Check against common passwords
        if self.check_common_passwords and is_common_password(password):
            errors.append('This password is too common. Please choose a more unique password')

        if errors:
            raise ValidationError('. '.join(errors) + '.')


def is_common_password(password):
    """
    Check if password is in the list of common/weak passwords.

    Args:
        password: Password to check

    Returns:
        bool: True if password is common, False otherwise
    """
    # Common passwords list (top 100+ most common)
    # In production, this should be loaded from a file or database
    common_passwords = {
        'password', 'password123', 'password1234', 'password12345', 'password123456',
        '12345678', '123456789', '1234567890',
        'qwerty', 'qwertyuiop', 'abc123', 'abcdefgh', 'letmein', 'welcome', 'welcome123',
        'admin', 'admin123', 'administrator', 'root', 'toor', 'pass', 'pass123',
        'Password1', 'Password123', 'Password1234', 'Password12345', 'Password123456',
        'Password@1', 'Password@12', 'Password@123', 'Password@1234', 'Password@12345', 'Password@123456',
        'user', 'user123', 'test', 'test123', 'demo', 'demo123',
        'monkey', 'dragon', 'master', 'trustno1', 'baseball', 'football',
        '1q2w3e4r', 'q1w2e3r4', 'zxcvbnm', 'asdfghjkl',
        'sunshine', 'shadow', 'ashley', 'bailey', 'passw0rd',
        'batman', 'superman', 'michael', 'jennifer', 'jordan',
        '000000', '111111', '222222', '123123', '654321',
        'iloveyou', 'princess', 'starwars', 'whatever', 'nothing',
        'password!', 'password@', 'password#', 'password$',
        'admin!', 'admin@', 'admin#', 'admin$',
        'Welcome1', 'Welcome123', 'Welcome@1', 'Welcome@123',
        'P@ssw0rd', 'P@ssword', 'P@ssword1', 'P@ssword123',
        'Qwerty123', 'Qwerty@123', 'Abc123456', 'Abc@123456',
        'computer', 'internet', 'samsung', 'liverpool', 'chelsea',
        'charlie', 'thomas', 'hunter', 'ranger', 'killer',
        'zaq1zaq1', 'zaq12wsx', 'xsw2zaq1', '1qaz2wsx',
        'qazwsxedc', 'qweasdzxc', 'zxcvbnm123', 'asdfghjkl123',
    }

    # Check password in lowercase (common passwords are case-insensitive)
    return password.lower() in common_passwords


class PasswordMatch:
    """
    WTForms validator to ensure password and confirm password fields match.

    Usage:
        confirm_password = PasswordField('Confirm Password', validators=[
            DataRequired(),
            PasswordMatch('password')
        ])
    """

    def __init__(self, field_name, message=None):
        """
        Initialize password match validator.

        Args:
            field_name: Name of the password field to compare against
            message: Custom error message (optional)
        """
        self.field_name = field_name
        self.message = message

    def __call__(self, form, field):
        """Validate that passwords match."""
        password_field = form._fields.get(self.field_name)

        if password_field is None:
            raise Exception(f'Invalid field name: {self.field_name}')

        if field.data != password_field.data:
            message = self.message or 'Passwords must match.'
            raise ValidationError(message)


def get_password_strength(password):
    """
    Get password strength score (0-100).

    Args:
        password: Password to evaluate

    Returns:
        int: Strength score (0-100)
    """
    if not password:
        return 0

    score = 0

    # Length score (up to 30 points)
    length = len(password)
    if length >= 12:
        score += 30
    elif length >= 8:
        score += 20
    elif length >= 6:
        score += 10

    # Complexity score (up to 40 points)
    if re.search(r'[a-z]', password):
        score += 10
    if re.search(r'[A-Z]', password):
        score += 10
    if re.search(r'\d', password):
        score += 10
    if re.search(r'[!@#$%^&*()_+\-=\[\]{};:\',.<>?/\\|`~]', password):
        score += 10

    # Variety score (up to 20 points)
    unique_chars = len(set(password))
    variety_ratio = unique_chars / length if length > 0 else 0
    score += int(variety_ratio * 20)

    # Penalty for common passwords
    if is_common_password(password):
        score = min(score, 30)  # Cap at 30 for common passwords

    # Ensure score is between 0-100
    return min(max(score, 0), 100)


def get_password_strength_label(score):
    """
    Get password strength label based on score.

    Args:
        score: Password strength score (0-100)

    Returns:
        str: Strength label ('weak', 'fair', 'good', 'strong', 'very strong')
    """
    if score < 30:
        return 'weak'
    elif score < 50:
        return 'fair'
    elif score < 70:
        return 'good'
    elif score < 90:
        return 'strong'
    else:
        return 'very strong'
