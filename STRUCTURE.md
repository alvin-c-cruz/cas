# CAS Application Structure

This Flask application follows the **Application Factory Pattern** with modular blueprints.

## Directory Structure

```
cas/
├── run.py                      # Application entry point
├── app/
│   ├── __init__.py            # Application factory (create_app)
│   ├── templates/             # Shared templates
│   │   └── base.html         # Base template with sidebar/topbar
│   ├── static/                # Static assets
│   │   ├── css/
│   │   │   └── style.css     # Main stylesheet
│   │   └── js/
│   │       ├── app.js        # Mock data & page logic
│   │       └── cas-ui.js     # UI utilities
│   ├── dashboard/             # Dashboard module
│   │   ├── __init__.py
│   │   ├── views.py          # Dashboard routes (blueprint)
│   │   └── templates/
│   │       └── dashboard/
│   │           └── index.html
│   └── accounts/              # Accounts module
│       ├── __init__.py
│       ├── models.py         # Account model
│       ├── views.py          # Accounts routes (blueprint)
│       └── templates/
│           └── accounts/
│               ├── list.html     # List all accounts
│               ├── form.html     # Create/Edit form
│               └── detail.html   # View account details
├── cas.db                     # SQLite database
└── requirements.txt           # Python dependencies
```

## Architecture Overview

### Application Factory Pattern

The application uses the factory pattern defined in `app/__init__.py`:

```python
from app import create_app

app = create_app()
```

**Benefits:**
- Easier testing (can create multiple app instances with different configs)
- Cleaner separation of concerns
- Better scalability

### Module Structure

Each feature is organized as a **module** (also called a blueprint):

```
module_name/
├── __init__.py       # Module initialization
├── models.py         # Database models
├── views.py          # Routes (blueprint)
└── templates/        # Module-specific templates
    └── module_name/
        └── *.html
```

### Current Modules

#### 1. **Dashboard Module** (`app/dashboard/`)
- **Blueprint:** `dashboard_bp`
- **URL Prefix:** None (root level)
- **Routes:**
  - `GET /` → Redirects to dashboard
  - `GET /dashboard` → Main dashboard page
- **Template:** `dashboard/index.html`

#### 2. **Accounts Module** (`app/accounts/`)
- **Blueprint:** `accounts_bp`
- **URL Prefix:** `/accounts`
- **Routes:**
  - `GET /accounts/` → List all accounts
  - `GET /accounts/create` → Show create form
  - `POST /accounts/create` → Create new account
  - `GET /accounts/<id>` → View account details
  - `GET /accounts/<id>/edit` → Show edit form
  - `POST /accounts/<id>/edit` → Update account
  - `POST /accounts/<id>/delete` → Delete account
- **Model:** `Account` (in `models.py`)
- **Templates:**
  - `accounts/list.html` - Chart of Accounts listing
  - `accounts/form.html` - Create/Edit form
  - `accounts/detail.html` - Account detail view

## Database Models

### Account Model (`app/accounts/models.py`)

```python
class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    account_type = db.Column(db.String(20), nullable=False)
    classification = db.Column(db.String(20))
    normal_balance = db.Column(db.String(10), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
```

## URL Routing

### Blueprint URL Naming Convention

When using blueprints, URLs are referenced as: `blueprint_name.function_name`

**Examples:**
```python
# Dashboard
url_for('dashboard.home')           # → /dashboard

# Accounts
url_for('accounts.list_accounts')   # → /accounts/
url_for('accounts.create')          # → /accounts/create
url_for('accounts.view', id=1)      # → /accounts/1
url_for('accounts.edit', id=1)      # → /accounts/1/edit
url_for('accounts.delete', id=1)    # → /accounts/1/delete
```

## Running the Application

### Development Server

```bash
# Start the application
python run.py
```

The server will start at **http://127.0.0.1:5000/**

### Initialization

On first run, the application will:
1. Create the database (`cas.db`)
2. Create all tables
3. Insert 12 sample accounts

## Adding New Modules

To add a new module (e.g., "Journal Entries"):

1. **Create module directory:**
   ```bash
   mkdir -p app/journal/templates/journal
   ```

2. **Create `__init__.py`:**
   ```python
   # app/journal/__init__.py
   ```

3. **Create models (if needed):**
   ```python
   # app/journal/models.py
   from app import db

   class JournalEntry(db.Model):
       # ... model definition
   ```

4. **Create views (blueprint):**
   ```python
   # app/journal/views.py
   from flask import Blueprint, render_template

   journal_bp = Blueprint('journal', __name__, template_folder='templates')

   @journal_bp.route('/')
   def list_entries():
       return render_template('journal/list.html')
   ```

5. **Create templates:**
   ```
   app/journal/templates/journal/list.html
   ```

6. **Register blueprint in `app/__init__.py`:**
   ```python
   from app.journal.views import journal_bp
   app.register_blueprint(journal_bp, url_prefix='/journal')
   ```

## Template Inheritance

All module templates extend the base template:

```html
{% extends "base.html" %}

{% block title %}Page Title{% endblock %}
{% block page_title %}Page Header{% endblock %}

{% block content %}
<!-- Module-specific content -->
{% endblock %}
```

The base template (`app/templates/base.html`) contains:
- Sidebar navigation
- Topbar
- Flash message display
- Common CSS/JS includes
- Scrollbar hiding styles

## Best Practices

1. **One module per feature** - Keep related functionality together
2. **Use blueprints** - Each module should have its own blueprint
3. **Template organization** - Module templates go in `module/templates/module_name/`
4. **URL naming** - Always use `url_for()` with blueprint names
5. **Database migrations** - For production, use Flask-Migrate (not implemented yet)
6. **Config management** - Pass config dict to `create_app()` for different environments

## Future Enhancements

- Add Flask-Migrate for database migrations
- Implement user authentication module
- Add Journal Entries module
- Add General Ledger module
- Implement API endpoints (RESTful)
- Add unit tests for each module
- Environment-specific configs (dev, staging, prod)
