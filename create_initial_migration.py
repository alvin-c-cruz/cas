"""
Create initial migration file for all models.

This script creates the initial migration by creating an empty database,
applying all models, and then generating the migration from the changes.
"""
import os
import sys
from app import create_app, db

def create_initial_migration():
    """Create initial migration from current models."""
    print("="*60)
    print("Creating Initial Migration")
    print("="*60)

    # Ensure database doesn't exist
    db_path = 'instance/cas.db'
    if os.path.exists(db_path):
        print(f"\n[!] Database exists at {db_path}")
        print("[!] Please delete it first or this script won't work properly.")
        return False

    print("\n[1] Creating empty database...")
    app = create_app()
    with app.app_context():
        # Create all tables from models
        db.create_all()
        print("[OK] Database created with all tables from models")

    print("\n[2] Now run this command to create the migration:")
    print("    set FLASK_APP=flask_app.py && flask db migrate -m \"Initial migration - all tables\"")

    print("\n[3] After migration is created, delete the database:")
    print("    del instance\\cas.db")

    print("\n[4] Then apply the migration:")
    print("    set FLASK_APP=flask_app.py && flask db upgrade")

    print("\n[5] Finally, load fixtures:")
    print("    python load_fixtures.py")

    print("\n" + "="*60)
    return True

if __name__ == '__main__':
    create_initial_migration()
