# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this Flask application.

## Project Overview

**CAS (Computerized Accounting System)** is a professional Flask web application for managing financial accounting operations for Philippine SMEs with BIR compliance features.

## Tech Stack

- **Backend Framework:** Flask 3.1.0 (Python)
- **Database:** SQLAlchemy 2.0.36 with SQLite
- **Forms:** Flask-WTF 1.2.2 & WTForms 3.2.1
- **Templating:** Jinja2 3.1.4
- **CSS:** Custom CSS with design tokens
- **JavaScript:** Vanilla JS (cas-ui.js utilities)

## Architecture Pattern

This application uses the **Application Factory Pattern** with **Blueprint-based modular architecture**.

### Directory Structure

```
cas/
├── run.py                      # Application entry point
├── app/
│   ├── __init__.py            # Application factory (create_app)
│   ├── templates/             # Shared templates
│   │   ├── base.html         # Base layout (sidebar, topbar)
│   │   └── macros.html       # Reusable Jinja2 macros
│   ├── static/                # Static assets
│   │   ├── css/style.css     # Design system CSS
│   │   └── js/
│   │       ├── app.js        # Mock data & page logic
│   │       └── cas-ui.js     # UI utilities (modals, tabs, forms)
│   ├── dashboard/             # Dashboard module
│   │   ├── __init__.py
│   │   ├── views.py          # Dashboard routes (blueprint)
│   │   └── templates/dashboard/
│   └── accounts/              # Chart of Accounts module
│       ├── __init__.py
│       ├── models.py         # Account model
│       ├── forms.py          # WTForms definitions
│       ├── views.py          # Accounts routes (blueprint)
│       └── templates/accounts/
├── cas.db                     # SQLite database
├── requirements.txt           # Python dependencies
├── CLAUDE.md                  # This file
├── DESIGN.md                  # Design system documentation
├── STRUCTURE.md               # Detailed architecture docs
└── README.md                  # Project README
```

## Development Guidelines

### 1. Module Organization

Each feature should be organized as a **module** (blueprint) with this structure:

```
module_name/
├── __init__.py       # Module initialization
├── models.py         # Database models (if needed)
├── forms.py          # WTForms (if needed)
├── views.py          # Routes (blueprint)
└── templates/        # Module-specific templates
    └── module_name/
        └── *.html
```

### 2. Creating New Modules

When adding a new feature module:

```python
# 1. Create module directory
mkdir -p app/module_name/templates/module_name

# 2. Create __init__.py
# app/module_name/__init__.py
# (empty or module config)

# 3. Create models (if needed)
# app/module_name/models.py
from app import db

class ModelName(db.Model):
    # model definition

# 4. Create forms (if needed)
# app/module_name/forms.py
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired

class MyForm(FlaskForm):
    field_name = StringField('Label', validators=[DataRequired()])

# 5. Create blueprint
# app/module_name/views.py
from flask import Blueprint, render_template
from app.module_name.forms import MyForm

module_bp = Blueprint('module_name', __name__, template_folder='templates')

@module_bp.route('/')
def index():
    return render_template('module_name/index.html')

# 6. Register in app/__init__.py
from app.module_name.views import module_bp
app.register_blueprint(module_bp, url_prefix='/module_name')
```

### 3. Database Models

- Place models in the module's `models.py`
- Import `db` from `app`
- Use descriptive table names: `__tablename__ = 'table_name'`
- Add `__repr__` method for debugging
- Consider adding `to_dict()` method for JSON serialization

**Example:**
```python
from app import db
from datetime import datetime

class Account(db.Model):
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Account {self.code}>'
```

### 4. Forms with Flask-WTF

- Use Flask-WTF for all forms
- Add CSRF protection: `{{ form.hidden_tag() }}`
- Use validators from `wtforms.validators`
- Place forms in module's `forms.py`

**Example:**
```python
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField
from wtforms.validators import DataRequired, Length

class AccountForm(FlaskForm):
    code = StringField('Code', validators=[DataRequired(), Length(max=20)])
    account_type = SelectField('Type', choices=[...])
```

### 5. Templates and Macros

**Use Macros for Reusability:**
```jinja2
{% from "macros.html" import render_field, render_flash_messages %}

{{ render_field(form.field_name) }}
{{ render_flash_messages() }}
```

**Template Inheritance:**
```jinja2
{% extends "base.html" %}

{% block title %}Page Title{% endblock %}
{% block page_title %}Header Title{% endblock %}

{% block content %}
<!-- Your content -->
{% endblock %}
```

### 6. URL Routing

Always use `url_for()` with blueprint namespace:

```jinja2
<!-- Correct -->
<a href="{{ url_for('accounts.list_accounts') }}">Accounts</a>
<a href="{{ url_for('accounts.edit', id=account.id) }}">Edit</a>

<!-- Incorrect -->
<a href="/accounts/">Accounts</a>
```

### 7. Flash Messages

Use categories for flash messages:

```python
flash('Success message', 'success')
flash('Error message', 'error')
flash('Info message', 'info')
flash('Warning message', 'warning')
```

Then render with:
```jinja2
{{ render_flash_messages() }}
```

### 8. Database Migrations with Flask-Migrate

**This project uses Flask-Migrate for database schema management.**

See [MIGRATIONS.md](MIGRATIONS.md) for complete documentation.

**Quick reference:**
```bash
# Set Flask app (required before each command)
set FLASK_APP=flask_app.py

# Create migration after model changes
flask db migrate -m "Description of changes"

# Apply migrations
flask db upgrade

# Rollback migration
flask db downgrade
```

### 9. Database Operations

**Creating records:**
```python
from app import db
from app.accounts.models import Account

account = Account(code='1000', name='Cash')
db.session.add(account)
db.session.commit()
```

**Querying:**
```python
# Get all
accounts = Account.query.all()

# Filter
account = Account.query.filter_by(code='1000').first()

# Get by ID
account = Account.query.get_or_404(id)

# Order by
accounts = Account.query.order_by(Account.code).all()
```

**Updating:**
```python
account = Account.query.get(id)
account.name = 'New Name'
db.session.commit()
```

**Deleting:**
```python
account = Account.query.get(id)
db.session.delete(account)
db.session.commit()
```

**Always wrap in try/except:**
```python
try:
    db.session.add(account)
    db.session.commit()
    flash('Success!', 'success')
except Exception as e:
    db.session.rollback()
    flash(f'Error: {str(e)}', 'error')
```

## Code Style Guidelines

### Python

- Follow PEP 8 style guide
- Use snake_case for functions and variables
- Use PascalCase for class names
- Docstrings for all functions and classes
- Type hints where appropriate

### HTML/Jinja2

- Use 4-space indentation
- Use double quotes for attributes
- Keep templates clean with macros
- Use semantic HTML

### CSS

- Use existing design tokens (CSS variables)
- Follow BEM-like naming where applicable
- Keep styles scoped to components
- Mobile-first responsive design

### JavaScript

- Use const/let (no var)
- Use arrow functions
- Keep functions small and focused
- Document complex logic

## Design System

Refer to `DESIGN.md` for complete design system documentation.

**Quick Reference:**

**Colors:**
- Blue (Primary): `#3b82f6`
- Green (Success): `#22c55e`
- Red (Error/Danger): `#ef4444`
- Amber (Warning): `#f59e0b`
- Purple (Equity): `#8b5cf6`

**Typography:**
- Font: Inter (Google Fonts)
- Base size: 14px

**Spacing:**
- Use multiples of 4px (4, 8, 12, 16, 20, 24...)

## Common Tasks

### Running the Application

```bash
python run.py
```

Application runs at `http://127.0.0.1:5000/`

### Database Migrations

Currently using `db.create_all()` for development. For production, consider adding Flask-Migrate:

```bash
pip install flask-migrate
```

### Adding Sample Data

Sample data seeding happens automatically in `app/__init__.py` on first run.

### Testing

**Manual Testing:**
1. Navigate to feature in browser
2. Test create/read/update/delete
3. Verify validation errors
4. Check flash messages
5. Test edge cases

## Important Conventions

### Model Conventions
- Primary key: `id` (Integer, auto-increment)
- Timestamps: `created_at`, `updated_at`
- Boolean fields: `is_*` (e.g., `is_active`)
- Foreign keys: `*_id` (e.g., `parent_id`)

### Form Conventions
- Form class name: `ModelNameForm` (e.g., `AccountForm`)
- Use `form.hidden_tag()` for CSRF
- Validate with `form.validate_on_submit()`
- Populate from model: `form = MyForm(obj=model)`
- Update model: `form.populate_obj(model)`

### Template Conventions
- Module templates in `module/templates/module_name/`
- List page: `list.html`
- Detail page: `detail.html`
- Form page: `form.html` (for both create and edit)
- Extend `base.html`
- Import macros: `{% from "macros.html" import ... %}`

### URL Conventions
- List: `/module/`
- Create: `/module/create`
- View: `/module/<id>`
- Edit: `/module/<id>/edit`
- Delete: `/module/<id>/delete` (POST only)

### Blueprint Naming
- Blueprint variable: `module_bp`
- Blueprint name: `'module_name'`
- Register with URL prefix: `/module_name`

## Philippine SME Context

This application is tailored for Philippine businesses:

- Currency: Philippine Peso (₱)
- Number format: 1,000,000.00
- BIR compliance features
- Local business practices

## Security Considerations

- CSRF protection enabled via Flask-WTF
- SQL injection prevented via SQLAlchemy ORM
- XSS prevented via Jinja2 auto-escaping
- Secret key should be environment variable in production
- Don't commit sensitive data to git

## Deployment Considerations

For production:
1. Use environment variables for config
2. Set `DEBUG = False`
3. Use production database (PostgreSQL)
4. Use gunicorn or uwsgi
5. Set up proper logging
6. Use Flask-Migrate for migrations
7. Implement proper authentication
8. Use HTTPS

## Getting Help

- Flask docs: https://flask.palletsprojects.com/
- SQLAlchemy docs: https://docs.sqlalchemy.org/
- WTForms docs: https://wtforms.readthedocs.io/
- Jinja2 docs: https://jinja.palletsprojects.com/

## Notes for Claude

- Always check existing patterns before creating new ones
- Use the application factory pattern
- Follow the modular blueprint architecture
- Use WTForms for all forms
- Use macros for reusable components
- Keep database operations in try/except blocks
- Flash messages for user feedback
- Use `url_for()` for all URLs
- Follow the established naming conventions
