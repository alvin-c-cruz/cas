# Database Migrations with Flask-Migrate

This document explains how to use Flask-Migrate for managing database schema changes in the CAS application.

## What is Flask-Migrate?

Flask-Migrate is an extension that handles SQLAlchemy database migrations using Alembic. It provides:
- **Version control** for database schema
- **Automatic migration generation** from model changes
- **Easy upgrade/downgrade** between schema versions
- **Team collaboration** through shared migration files

## Setup (Already Done)

Flask-Migrate has been installed and configured for this project:

1. ✅ Package installed: `Flask-Migrate==4.1.0`
2. ✅ Initialized in `app/__init__.py`
3. ✅ Migrations directory created: `migrations/`
4. ✅ Initial migration created and stamped

## Common Commands

### Windows (cmd.exe or PowerShell)
```bash
# Set Flask app environment variable (required before each command)
set FLASK_APP=flask_app.py

# Check current migration status
flask db current

# View migration history
flask db history

# Create a new migration after model changes
flask db migrate -m "Description of changes"

# Apply pending migrations
flask db upgrade

# Rollback to previous migration
flask db downgrade

# Rollback to specific migration
flask db downgrade <revision>

# Show SQL that would be executed (without running it)
flask db upgrade --sql
```

### Unix/Mac/Linux
```bash
export FLASK_APP=flask_app.py
flask db migrate -m "Description"
flask db upgrade
```

## Typical Workflow

### 1. Making Model Changes

When you need to add/modify database models:

```python
# Example: Adding a new field to User model
class User(UserMixin, db.Model):
    # ... existing fields ...
    phone_number = db.Column(db.String(20))  # New field
```

### 2. Generate Migration

```bash
set FLASK_APP=flask_app.py
flask db migrate -m "Add phone number to User model"
```

This creates a new migration file in `migrations/versions/` with:
- `upgrade()` function - applies changes
- `downgrade()` function - reverts changes

### 3. Review Migration File

**IMPORTANT**: Always review the generated migration file before applying it!

Location: `migrations/versions/XXXXX_description.py`

Check:
- Are all changes captured correctly?
- Are there any data transformations needed?
- Should you add custom logic?

### 4. Apply Migration

```bash
flask db upgrade
```

This applies the migration to your database.

### 5. Commit to Version Control

```bash
git add migrations/versions/XXXXX_description.py
git commit -m "Add phone number to User model"
```

## Examples

### Example 1: Adding a New Table

**1. Create the model:**
```python
# app/transactions/models.py
from app import db
from datetime import datetime

class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.String(500))
```

**2. Generate migration:**
```bash
set FLASK_APP=flask_app.py
flask db migrate -m "Add Transaction model"
```

**3. Apply migration:**
```bash
flask db upgrade
```

### Example 2: Adding a Column

**1. Modify model:**
```python
class Branch(db.Model):
    # ... existing columns ...
    tax_id = db.Column(db.String(50))  # New column
```

**2. Generate migration:**
```bash
set FLASK_APP=flask_app.py
flask db migrate -m "Add tax_id to Branch"
```

**3. Review the migration file** (migrations/versions/XXXXX_add_tax_id_to_branch.py)

**4. Apply migration:**
```bash
flask db upgrade
```

### Example 3: Modifying a Column

**1. Change model:**
```python
class Account(db.Model):
    # Old: code = db.Column(db.String(20))
    code = db.Column(db.String(50))  # Increased length
```

**2. Generate migration:**
```bash
flask db migrate -m "Increase account code length to 50"
```

**3. For SQLite (limitation):** You may need to manually edit the migration
```python
def upgrade():
    # SQLite doesn't support ALTER COLUMN directly
    # May need to create new table and copy data
    pass

def downgrade():
    pass
```

**4. Apply:**
```bash
flask db upgrade
```

## Rollback Example

If you need to undo a migration:

```bash
set FLASK_APP=flask_app.py

# Rollback one migration
flask db downgrade

# Rollback to specific revision
flask db history  # Get revision ID
flask db downgrade abc123def456
```

## Best Practices

### 1. Always Review Generated Migrations
- Flask-Migrate auto-generates migrations but may miss complex changes
- Review before applying to production

### 2. Test Migrations
```bash
# Test upgrade
flask db upgrade

# Test downgrade
flask db downgrade

# Re-upgrade
flask db upgrade
```

### 3. Never Edit Applied Migrations
- Once a migration is applied and committed, don't edit it
- Create a new migration instead

### 4. Backup Before Migrating Production
```bash
# Backup database first
cp instance/cas.db instance/cas.db.backup

# Then migrate
flask db upgrade
```

### 5. Use Descriptive Messages
```bash
# Good
flask db migrate -m "Add branch_id foreign key to users table"

# Bad
flask db migrate -m "update"
```

### 6. Keep Migrations Small
- One logical change per migration
- Easier to review, test, and rollback

## Troubleshooting

### Migration Not Detecting Changes

**Problem**: `flask db migrate` says "No changes detected"

**Solutions**:
1. Make sure models are imported in `app/__init__.py` or `migrations/env.py`
2. Ensure `db` instance is the same one used in models
3. Try running with verbose output: `flask db migrate -m "msg" --verbose`

### SQLite Limitations

SQLite has limited ALTER TABLE support:
- Can't rename columns
- Can't drop columns (except in newer versions)
- Can't modify column types easily

**Workaround**: Create new table, copy data, drop old table, rename new table

### Merge Conflicts in Migrations

If multiple people create migrations:

```bash
# Create a merge migration
flask db merge heads -m "Merge migrations"
flask db upgrade
```

## Migration File Structure

```
cas/
├── migrations/
│   ├── versions/
│   │   ├── 93c3786e7e12_initial_migration.py
│   │   └── abc123def456_add_field.py
│   ├── alembic.ini
│   ├── env.py
│   ├── README
│   └── script.py.mako
├── instance/
│   └── cas.db
└── flask_app.py
```

## Current Database Schema

The current migration includes these tables:

1. **users** - User accounts with authentication
   - Includes `branch_id` foreign key to branches
2. **login_history** - User login audit trail
3. **accounts** - Chart of Accounts
4. **branches** - Branch/location management
5. **app_settings** - Application-wide settings

## Future Migration Examples

When you need to make changes:

```bash
# Add a new module (e.g., Journal Entries)
flask db migrate -m "Add journal entries table"

# Modify relationships
flask db migrate -m "Add customer_id to transactions"

# Add indexes for performance
flask db migrate -m "Add index on account code"

# Data migrations
flask db migrate -m "Populate default branch for existing users"
```

## Resources

- [Flask-Migrate Documentation](https://flask-migrate.readthedocs.io/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Migration Guide](https://docs.sqlalchemy.org/en/latest/core/metadata.html)

## Summary

Flask-Migrate is now fully set up and ready to use. For any database schema changes:

1. Modify your models
2. Run `flask db migrate -m "description"`
3. Review the generated migration
4. Run `flask db upgrade`
5. Commit the migration file to git

This ensures safe, version-controlled database changes across all environments!
