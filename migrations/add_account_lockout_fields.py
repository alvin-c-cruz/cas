"""
Database migration to add account lockout fields to User model.

This migration adds:
- failed_login_attempts: Counter for failed login attempts
- account_locked_until: Timestamp until which account is locked
- last_failed_login: Timestamp of last failed login

Usage:
    cd envs/cas
    python -c "import sys; sys.path.insert(0, '.'); exec(open('migrations/add_account_lockout_fields.py').read())"
"""

import sys
import os

# Add the current directory to the path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text

def run_migration():
    """Add account lockout fields to users table."""
    app = create_app()

    with app.app_context():
        try:
            print("Adding account lockout fields to users table...")

            # Add failed_login_attempts column (default 0)
            db.session.execute(text(
                "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0 NOT NULL"
            ))
            print("✓ Added failed_login_attempts column")

            # Add account_locked_until column (nullable)
            db.session.execute(text(
                "ALTER TABLE users ADD COLUMN account_locked_until DATETIME"
            ))
            print("✓ Added account_locked_until column")

            # Add last_failed_login column (nullable)
            db.session.execute(text(
                "ALTER TABLE users ADD COLUMN last_failed_login DATETIME"
            ))
            print("✓ Added last_failed_login column")

            db.session.commit()
            print("\n✓ Migration completed successfully!")
            print("\nAccount lockout features:")
            print("- Failed login attempts are now tracked")
            print("- Accounts will lock after 5 failed attempts")
            print("- Lockout duration: 15 minutes")
            print("- Admins can manually unlock accounts")

        except Exception as e:
            db.session.rollback()
            print(f"\n✗ Migration failed: {str(e)}")
            print("\nNote: If columns already exist, you can safely ignore this error.")
            raise

if __name__ == '__main__':
    run_migration()
