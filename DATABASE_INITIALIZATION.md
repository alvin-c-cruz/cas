# Database Initialization Guide

This document explains how to initialize and recreate the CAS application database with all default fixtures.

## Overview

The CAS application provides multiple ways to initialize the database:

1. **Automatic Initialization** - On first run via `flask_app.py`
2. **Interactive Initialization** - Using `init_db.py` script
3. **Migration-Based Recreation** - Using `recreate_db_with_migrations.py` (RECOMMENDED)

All methods use the centralized fixtures module (`app/fixtures.py`) to ensure consistent default data.

## Default Fixtures

When the database is initialized, the following default data is automatically loaded:

### 1. Default Admin User
- **Username**: `admin`
- **Password**: `admin123`
- **Email**: `admin@cas.local`
- **Full Name**: System Administrator
- **Role**: Admin
- **Status**: Active

⚠️ **IMPORTANT**: Change the admin password immediately after first login!

### 2. Sample Chart of Accounts
18 accounts across all account types:

**Assets (1000-1999)**
- 1000 - Cash on Hand
- 1100 - Cash in Bank
- 1200 - Accounts Receivable
- 1300 - Inventory
- 1400 - Prepaid Expenses
- 1500 - Property, Plant & Equipment

**Liabilities (2000-2999)**
- 2000 - Accounts Payable
- 2100 - Notes Payable
- 2200 - Accrued Expenses
- 2300 - Unearned Revenue

**Equity (3000-3999)**
- 3000 - Capital
- 3100 - Retained Earnings
- 3200 - Drawings

**Revenue (4000-4999)**
- 4000 - Sales Revenue
- 4100 - Service Revenue
- 4200 - Other Income

**Expenses (5000-5999)**
- 5000 - Cost of Goods Sold
- 5100 - Operating Expenses

### 3. Default Main Branch
- **Code**: MAIN
- **Name**: Main Office
- **Status**: Active

### 4. Default Application Settings
- **Environment Badge**: dev
- **Updated By**: System

## Method 1: Automatic Initialization

The application automatically initializes the database on first run.

**Usage:**
```bash
python flask_app.py
```

**What happens:**
1. Flask creates the `instance/` directory if it doesn't exist
2. `db.create_all()` creates all tables
3. Fixtures are loaded automatically (if tables are empty)
4. Application starts at http://127.0.0.1:5000/

**When to use:**
- First time running the application
- Database doesn't exist yet
- You want zero-configuration setup

## Method 2: Interactive Initialization

Use the `init_db.py` script for interactive database setup with user prompts.

**Usage:**
```bash
python init_db.py
```

**Features:**
- Detects if database already exists
- Offers multiple options based on current state
- Requires confirmation for destructive operations
- Provides detailed feedback

**Scenarios:**

### Scenario A: Database Does Not Exist
```
============================================================
Database Initialization
============================================================

  ℹ No database found at instance/cas.db

→ Creating database tables...
  ✓ Database tables created successfully

============================================================
Loading Default Fixtures
============================================================

  ✓ Default admin user created (username: admin, password: admin123)
  ✓ 18 sample accounts created
  ✓ Default main branch created
  ✓ Default settings initialized

============================================================
✓ Database Initialized Successfully!
============================================================
```

### Scenario B: Database Exists with Missing Fixtures
```
============================================================
Database Initialization
============================================================

  ℹ Database already exists at instance/cas.db

What would you like to do?

  1. Load missing fixtures only (safe - won't delete existing data)
  2. Delete database and recreate from scratch
  3. Cancel

Enter your choice (1, 2, or 3): 1

→ Loading missing fixtures...
  ℹ Admin user already exists, skipping...
  ℹ Accounts already exist, skipping...
  ✓ Default main branch created
  ✓ Default settings initialized
```

### Scenario C: Full Database Recreation
```
Enter your choice (1, 2, or 3): 2

⚠  WARNING: This will DELETE ALL DATA in the database!

Type 'DELETE' to confirm: DELETE

→ Deleting existing database...
  ✓ Deleted instance/cas.db

→ Creating fresh database...
  ✓ Database tables created successfully

→ Loading fixtures...
  ✓ Default admin user created
  ✓ 18 sample accounts created
  ✓ Default main branch created
  ✓ Default settings initialized

============================================================
✓ Database Initialized Successfully!
============================================================
```

**When to use:**
- You want control over what happens
- You need to add missing fixtures without losing data
- You prefer interactive confirmation

## Method 3: Migration-Based Recreation (RECOMMENDED)

Use `recreate_db_with_migrations.py` for proper version-controlled database recreation.

**Usage:**
```bash
python recreate_db_with_migrations.py
```

**Why this method is recommended:**
- Uses Flask-Migrate for proper schema versioning
- Ensures database matches migration files
- Best practice for team collaboration
- Safer for production deployment preparation

**Process:**
```
============================================================
Recreate Database Using Flask-Migrate
============================================================

⚠  WARNING: This will DELETE ALL DATA in the database!
⚠  The database will be recreated from scratch using migrations.

Type 'DELETE' to confirm: DELETE

→ Deleting existing database...
  ✓ Deleted instance/cas.db

============================================================
Running Flask-Migrate to Create Tables
============================================================

→ Applying migrations to create database schema...
  INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
  INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
  INFO  [alembic.runtime.migration] Running upgrade  -> 93c3786e7e12, Initial migration

============================================================
Loading Default Fixtures
============================================================

  ✓ Default admin user created (username: admin, password: admin123)
  ✓ 18 sample accounts created
  ✓ Default main branch created
  ✓ Default settings initialized

============================================================
✓ Database Successfully Recreated!
============================================================

Database recreated with:
  • All tables from migrations
  • Default admin user (admin/admin123)
  • Sample chart of accounts
  • Default main branch
  • Default application settings

============================================================
Next Steps:
============================================================

1. Start the application:
   python flask_app.py

2. Log in with:
   Username: admin
   Password: admin123

3. CHANGE THE ADMIN PASSWORD!

============================================================
```

**When to use:**
- You want the most reliable recreation method
- You're preparing for production deployment
- You need to ensure schema matches migrations
- Multiple developers are working on the project

## Fixtures Module Reference

All default data is managed in `app/fixtures.py`:

### Function: `load_default_admin()`
Creates the default admin user if it doesn't exist.

```python
from app import create_app
from app.fixtures import load_default_admin

app = create_app()
with app.app_context():
    admin = load_default_admin()
```

**Returns**: User object or None if already exists

### Function: `load_sample_chart_of_accounts()`
Creates 18 sample accounts across all account types.

```python
from app.fixtures import load_sample_chart_of_accounts

app = create_app()
with app.app_context():
    accounts = load_sample_chart_of_accounts()
```

**Returns**: List of Account objects (empty list if already exists)

### Function: `load_default_branch()`
Creates the default "Main Office" branch.

```python
from app.fixtures import load_default_branch

app = create_app()
with app.app_context():
    branch = load_default_branch()
```

**Returns**: Branch object or None if already exists

### Function: `load_default_settings()`
Initializes default application settings (environment badge, etc.).

```python
from app.fixtures import load_default_settings

app = create_app()
with app.app_context():
    load_default_settings()
```

**Returns**: None

### Function: `load_all_fixtures()`
Loads all fixtures in the correct order with formatted output.

```python
from app.fixtures import load_all_fixtures

app = create_app()
with app.app_context():
    load_all_fixtures()
```

**Output Example:**
```
============================================================
Loading Default Fixtures
============================================================

  ✓ Default admin user created (username: admin, password: admin123)
  ✓ 18 sample accounts created
  ✓ Default main branch created
  ✓ Default settings initialized

============================================================
```

## Customizing Default Data

To customize the default fixtures, edit `app/fixtures.py`:

### Example: Change Default Admin Credentials

```python
def load_default_admin():
    """Create default admin user."""
    if User.query.filter_by(username='admin').first():
        print("  ℹ Admin user already exists, skipping...")
        return None

    admin = User(
        username='myadmin',           # Changed
        email='admin@mycompany.com',  # Changed
        full_name='My Administrator', # Changed
        role='admin',
        is_active=True
    )
    admin.set_password('mypassword123')  # Changed
    db.session.add(admin)
    db.session.commit()
    print(f"  ✓ Default admin user created (username: myadmin, password: mypassword123)")
    return admin
```

### Example: Add More Default Accounts

```python
def load_sample_chart_of_accounts():
    """Create sample chart of accounts."""
    if Account.query.count() > 0:
        print("  ℹ Accounts already exist, skipping...")
        return []

    accounts_data = [
        # ... existing accounts ...

        # Add new accounts here
        {
            'code': '1600',
            'name': 'Long-term Investments',
            'account_type': 'asset',
            'parent_code': None,
            'is_active': True
        },
        # ... more accounts ...
    ]

    # ... rest of function ...
```

## Troubleshooting

### Issue: "No such table: users"

**Problem**: Database tables don't exist.

**Solution**: Run database initialization:
```bash
python recreate_db_with_migrations.py
```

### Issue: "Admin user already exists"

**Problem**: Trying to create duplicate admin user.

**Solution**: This is normal - the fixture detects existing data and skips creation. If you need to reset the admin password:

```bash
python flask_app.py
# Then log in as any admin user and go to Users > Edit > Reset Password
```

Or use the Flask shell:
```bash
set FLASK_APP=flask_app.py
flask shell
```
```python
>>> from app.users.models import User
>>> admin = User.query.filter_by(username='admin').first()
>>> admin.set_password('newpassword')
>>> db.session.commit()
```

### Issue: "Database is locked"

**Problem**: Another process is using the database.

**Solution**:
1. Close any running Flask development servers
2. Close any database browser tools (DB Browser for SQLite, etc.)
3. Try again

### Issue: "Migration not found"

**Problem**: Migrations directory is missing or corrupt.

**Solution**:
```bash
# Reinitialize migrations (only if safe to do so)
set FLASK_APP=flask_app.py
flask db init

# Create new initial migration
flask db migrate -m "Initial migration"

# Apply migration
flask db upgrade
```

### Issue: "ImportError: cannot import name 'load_all_fixtures'"

**Problem**: Fixtures module not found.

**Solution**: Ensure `app/fixtures.py` exists in your project. If missing, restore from version control or recreate using the templates in this documentation.

## Integration with Flask-Migrate

The fixtures system works seamlessly with Flask-Migrate:

### Workflow for Schema Changes

1. **Modify models** in `app/*/models.py`
2. **Create migration**:
   ```bash
   set FLASK_APP=flask_app.py
   flask db migrate -m "Add new field to User"
   ```
3. **Review migration** in `migrations/versions/`
4. **Apply migration**:
   ```bash
   flask db upgrade
   ```
5. **Fixtures still work** - they only create data if tables are empty

### Workflow for Fresh Database

1. **Delete database**:
   ```bash
   del instance\cas.db
   ```
2. **Recreate from migrations**:
   ```bash
   python recreate_db_with_migrations.py
   ```
3. **Fixtures load automatically**

### Workflow for Production Deployment

1. **Backup production database**:
   ```bash
   copy instance\cas.db instance\cas.db.backup
   ```
2. **Run migrations**:
   ```bash
   set FLASK_APP=flask_app.py
   flask db upgrade
   ```
3. **Fixtures won't duplicate** existing data (they check first)

## Best Practices

### 1. Always Use Migration-Based Recreation in Development

Prefer `recreate_db_with_migrations.py` over `init_db.py` to ensure your database matches migration files.

### 2. Never Manually Edit Fixtures After Initial Deployment

Once you've deployed to production, don't modify default fixtures. Create new migrations for data changes instead.

### 3. Backup Before Recreating

Always backup before running destructive operations:
```bash
copy instance\cas.db instance\cas.db.backup
```

### 4. Change Default Admin Password

Immediately after initialization, log in and change the admin password:
1. Log in as admin/admin123
2. Click user info in topbar
3. Select "Change password"
4. Set a strong password

### 5. Test Fixture Loading

Periodically test fixture loading to ensure they still work:
```bash
del instance\cas.db
python recreate_db_with_migrations.py
python flask_app.py
# Verify all features work
```

### 6. Keep Fixtures Minimal

Only include essential default data in fixtures:
- ✅ Admin user (required for first login)
- ✅ Sample chart of accounts (helps users understand the system)
- ✅ Default branch (required for multi-branch system)
- ✅ Default settings (required for environment badge)
- ❌ Test data (create separately for development)
- ❌ Production data (migrate separately)

### 7. Document Custom Fixtures

If you add custom fixtures, document them in this file:
```markdown
### 5. Custom Customer Categories
- Category A - Retail Customers
- Category B - Wholesale Customers
- Category C - VIP Customers
```

## Security Considerations

### Default Admin Password

The default admin password (`admin123`) is **intentionally weak** to force users to change it.

**In production:**
1. Change admin password immediately
2. Consider requiring password change on first login
3. Implement password complexity requirements
4. Enable audit logging (already enabled via LoginHistory)

### Database File Permissions

The SQLite database file should have restricted permissions:

**Windows:**
```bash
# Right-click instance\cas.db > Properties > Security
# Ensure only authorized users have access
```

**Unix/Mac:**
```bash
chmod 600 instance/cas.db
chown appuser:appgroup instance/cas.db
```

### Environment Variables for Production

Never hardcode sensitive data in fixtures for production:

```python
# Bad (hardcoded)
admin.set_password('admin123')

# Good (from environment)
import os
default_password = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'admin123')
admin.set_password(default_password)
```

## Related Documentation

- [MIGRATIONS.md](MIGRATIONS.md) - Flask-Migrate usage guide
- [FLASK_MIGRATE_SETUP.md](FLASK_MIGRATE_SETUP.md) - Setup summary
- [CLAUDE.md](CLAUDE.md) - Development guidelines
- [README.md](README.md) - Project overview

## Summary

The CAS application provides three methods for database initialization:

| Method | Use Case | Automation Level | Version Control |
|--------|----------|------------------|-----------------|
| **Automatic** (flask_app.py) | First run, development | Full | No |
| **Interactive** (init_db.py) | Selective fixture loading | Partial | No |
| **Migration-based** (recreate_db_with_migrations.py) | Production prep, team dev | Full | Yes ✓ |

**Recommended approach:** Use `recreate_db_with_migrations.py` for all database recreation to ensure consistency with migration files.

All methods use the centralized `app/fixtures.py` module to load default data:
- Default admin user (admin/admin123)
- Sample chart of accounts (18 accounts)
- Default main branch
- Default application settings

The fixtures system integrates seamlessly with Flask-Migrate and is designed to be idempotent (safe to run multiple times without duplicating data).
