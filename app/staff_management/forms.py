from flask_wtf import FlaskForm
from wtforms import SelectField, SelectMultipleField, BooleanField
from wtforms.validators import DataRequired


class StaffEditForm(FlaskForm):
    """Accountant-scoped edit of a staff/viewer. Role choices exclude admin and
    accountant so a forged value is rejected by WTForms. Permissions are handled
    via raw `book_<key>` checkboxes in the view (mirrors the admin user form)."""
    role = SelectField('Role', choices=[('viewer', 'Viewer'), ('staff', 'Staff')],
                       validators=[DataRequired()])
    branch_ids = SelectMultipleField('Branch Assignment', coerce=int)
    is_active = BooleanField('Active')
