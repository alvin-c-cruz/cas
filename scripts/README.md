# Utility Scripts

This directory contains utility and maintenance scripts for the CAS application.

## Database Scripts

- `init_db.py` - Initialize database with all tables
- `create_initial_migration.py` - Create initial Flask-Migrate migration
- `init_migrations.py` - Initialize Flask-Migrate for the project
- `generate_migration_from_models.py` - Generate migration from existing models
- `recreate_db_with_migrations.py` - Recreate database using migrations
- `load_fixtures.py` - Load initial fixture data

## Table Creation Scripts

- `add_book_permissions.py` - Add book permissions table
- `add_branches_support.py` - Add branches support to database
- `add_login_history_table.py` - Create login history table
- `create_settings_table.py` - Create settings table
- `create_notifications_table.py` - Create notifications table
- `migrate_add_branches.py` - Migration script for adding branches

## Data Generation Scripts

- `create_manufacturing_coa.py` - Create manufacturing chart of accounts
- `generate_sample_login_history.py` - Generate sample login history data

## Testing & Verification Scripts

- `test_login.py` - Test login functionality
- `test_timezone.py` - Test timezone settings
- `test_audit_customer.py` - Test customer audit functionality
- `verify_accounts.py` - Verify accounts data
- `check_audit.py` - Check audit log functionality
- `check_requests.py` - Check change requests
- `check_tables.py` - Check database tables

## Maintenance Scripts

- `reset_admin.py` - Reset admin password

## Usage

Most scripts can be run directly from the project root:

```bash
python scripts/script_name.py
```

Make sure to activate the virtual environment first:

```bash
# Windows
venv\Scripts\activate

# Unix/Mac
source venv/bin/activate
```