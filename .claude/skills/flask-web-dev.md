---
name: Flask Web Development
description: Expert Flask web development with best practices for building production-ready applications
---

# Flask Web Development Skill

This skill provides expert guidance for Flask web application development following industry best practices.

## Expertise Areas

### 1. Application Factory Pattern

Create scalable Flask applications using the application factory pattern:

```python
# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def create_app(config=None):
    app = Flask(__name__)

    # Configuration
    app.config['SECRET_KEY'] = 'your-secret-key'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions
    db.init_app(app)

    # Register blueprints
    from app.module.views import module_bp
    app.register_blueprint(module_bp, url_prefix='/module')

    # Create tables
    with app.app_context():
        db.create_all()

    return app
```

### 2. Blueprint-Based Modular Architecture

Organize features as self-contained modules:

```
app/
├── __init__.py              # Application factory
├── templates/               # Shared templates
│   ├── base.html
│   └── macros.html
├── static/                  # Static assets
└── module_name/             # Feature module
    ├── __init__.py
    ├── models.py           # Database models
    ├── forms.py            # WTForms
    ├── views.py            # Routes (blueprint)
    └── templates/
        └── module_name/
```

**Blueprint Creation:**

```python
# app/module_name/views.py
from flask import Blueprint, render_template

module_bp = Blueprint('module_name', __name__, template_folder='templates')

@module_bp.route('/')
def index():
    return render_template('module_name/index.html')
```

### 3. Database Models with SQLAlchemy

Create robust database models:

```python
from app import db
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    posts = db.relationship('Post', backref='author', lazy='dynamic')

    def __repr__(self):
        return f'<User {self.username}>'

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email
        }
```

**Common Patterns:**
- Primary key: `id` (Integer, auto-increment)
- Timestamps: `created_at`, `updated_at`
- Soft deletes: `is_deleted`, `deleted_at`
- Active status: `is_active`

### 4. Forms with Flask-WTF

Create secure, validated forms:

```python
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo

class RegistrationForm(FlaskForm):
    username = StringField('Username',
                          validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email',
                       validators=[DataRequired(), Email()])
    password = PasswordField('Password',
                            validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password',
                                    validators=[DataRequired(), EqualTo('password')])
    agree_to_terms = BooleanField('I agree to terms',
                                 validators=[DataRequired()])
```

**In Views:**

```python
@module_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()

    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data
        )
        db.session.add(user)
        db.session.commit()
        flash('Registration successful!', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)
```

### 5. Template Macros for Reusability

Create reusable template components:

```jinja2
{# app/templates/macros.html #}

{% macro render_field(field, label_class='', input_class='') %}
<div class="form-group">
    {{ field.label(class=label_class or 'form-label') }}
    {{ field(class=input_class or 'form-control') }}

    {% if field.errors %}
        <div class="field-errors">
            {% for error in field.errors %}
                <span class="error-message">{{ error }}</span>
            {% endfor %}
        </div>
    {% endif %}
</div>
{% endmacro %}

{% macro render_flash_messages() %}
{% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
        {% for category, message in messages %}
        <div class="alert alert-{{ category }}">
            {{ message }}
        </div>
        {% endfor %}
    {% endif %}
{% endwith %}
{% endmacro %}
```

**Usage:**

```jinja2
{% from "macros.html" import render_field, render_flash_messages %}

{{ render_flash_messages() }}

<form method="POST">
    {{ form.hidden_tag() }}
    {{ render_field(form.username) }}
    {{ render_field(form.email) }}
</form>
```

### 6. Database Operations Best Practices

**Create:**
```python
try:
    user = User(username='john', email='john@example.com')
    db.session.add(user)
    db.session.commit()
    flash('User created!', 'success')
except Exception as e:
    db.session.rollback()
    flash(f'Error: {str(e)}', 'error')
```

**Read:**
```python
# Get all
users = User.query.all()

# Filter
user = User.query.filter_by(username='john').first()

# Get by ID (404 if not found)
user = User.query.get_or_404(id)

# Complex queries
users = User.query.filter(
    User.created_at >= datetime(2024, 1, 1)
).order_by(User.username).limit(10).all()
```

**Update:**
```python
try:
    user = User.query.get_or_404(id)
    user.username = new_username
    db.session.commit()
except Exception as e:
    db.session.rollback()
    flash(f'Error: {str(e)}', 'error')
```

**Delete:**
```python
try:
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
except Exception as e:
    db.session.rollback()
    flash(f'Error: {str(e)}', 'error')
```

### 7. URL Routing Best Practices

**RESTful Routes:**
```python
@module_bp.route('/')                        # GET  - List
@module_bp.route('/create', methods=['GET', 'POST'])  # GET/POST - Create
@module_bp.route('/<int:id>')                # GET  - View
@module_bp.route('/<int:id>/edit', methods=['GET', 'POST'])  # GET/POST - Edit
@module_bp.route('/<int:id>/delete', methods=['POST'])  # POST - Delete
```

**Always use `url_for()`:**
```jinja2
<a href="{{ url_for('module.index') }}">List</a>
<a href="{{ url_for('module.view', id=item.id) }}">View</a>
<a href="{{ url_for('module.edit', id=item.id) }}">Edit</a>
```

### 8. Flash Messages

```python
from flask import flash

# Success
flash('Operation successful!', 'success')

# Error
flash('An error occurred!', 'error')

# Info
flash('Please note: ...', 'info')

# Warning
flash('Warning: ...', 'warning')
```

### 9. Error Handling

**Custom Error Pages:**

```python
@app.errorhandler(404)
def page_not_found(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500
```

### 10. Configuration Management

```python
# config.py
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
```

## Common Patterns

### CRUD Operations Template

```python
from flask import Blueprint, render_template, redirect, url_for, flash
from app import db
from app.module.models import Item
from app.module.forms import ItemForm

module_bp = Blueprint('module', __name__, template_folder='templates')

@module_bp.route('/')
def list():
    items = Item.query.all()
    return render_template('module/list.html', items=items)

@module_bp.route('/create', methods=['GET', 'POST'])
def create():
    form = ItemForm()
    if form.validate_on_submit():
        item = Item()
        form.populate_obj(item)
        db.session.add(item)
        db.session.commit()
        flash('Created successfully!', 'success')
        return redirect(url_for('module.list'))
    return render_template('module/form.html', form=form)

@module_bp.route('/<int:id>')
def view(id):
    item = Item.query.get_or_404(id)
    return render_template('module/detail.html', item=item)

@module_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = Item.query.get_or_404(id)
    form = ItemForm(obj=item)
    if form.validate_on_submit():
        form.populate_obj(item)
        db.session.commit()
        flash('Updated successfully!', 'success')
        return redirect(url_for('module.list'))
    return render_template('module/form.html', form=form, item=item)

@module_bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    item = Item.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash('Deleted successfully!', 'success')
    return redirect(url_for('module.list'))
```

## Best Practices

1. **Security**
   - Always use CSRF protection (Flask-WTF)
   - Use SQLAlchemy ORM (prevents SQL injection)
   - Never commit secrets to version control
   - Use environment variables for sensitive config

2. **Database**
   - Always wrap DB operations in try/except
   - Rollback on errors
   - Use transactions for multi-step operations
   - Add indexes for frequently queried fields

3. **Forms**
   - Use Flask-WTF for all forms
   - Add proper validators
   - Display field-level errors
   - Use CSRF tokens

4. **Templates**
   - Extend base template
   - Use macros for reusable components
   - Always use `url_for()` for URLs
   - Escape user input (Jinja2 does this by default)

5. **Code Organization**
   - One blueprint per feature
   - Keep views thin, logic in models/services
   - Use meaningful variable names
   - Add docstrings

6. **Performance**
   - Use `lazy='dynamic'` for large relationships
   - Implement pagination for large datasets
   - Cache expensive queries
   - Optimize database queries

## Deployment Checklist

- [ ] Set `DEBUG = False`
- [ ] Use production database (PostgreSQL/MySQL)
- [ ] Set strong `SECRET_KEY`
- [ ] Use environment variables for config
- [ ] Set up logging
- [ ] Use gunicorn/uwsgi
- [ ] Set up database migrations (Flask-Migrate)
- [ ] Configure static file serving
- [ ] Set up SSL/HTTPS
- [ ] Implement rate limiting
- [ ] Add health check endpoint

## Common Extensions

```python
# Flask-Login - User authentication
from flask_login import LoginManager, login_user, logout_user, login_required

# Flask-Migrate - Database migrations
from flask_migrate import Migrate

# Flask-Mail - Email support
from flask_mail import Mail, Message

# Flask-Caching - Caching
from flask_caching import Cache
```

## Troubleshooting

**Database locked (SQLite):**
- Use PostgreSQL for production
- Check for uncommitted transactions
- Increase timeout

**CSRF token missing:**
- Include `{{ form.hidden_tag() }}` in form
- Ensure SECRET_KEY is set

**404 on static files:**
- Check static_folder path
- Use `url_for('static', filename='...')`

**Import errors:**
- Check circular imports
- Verify module structure
- Use absolute imports

This skill helps build production-ready Flask applications with clean architecture, security, and best practices.
