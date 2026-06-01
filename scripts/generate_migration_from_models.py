"""
Generate migration file content from current SQLAlchemy models.

This script creates a database with all models, then uses flask db migrate
to generate the proper migration content.
"""
import os
import subprocess
import sys

def main():
    print("="*60)
    print("Generate Migration from Models")
    print("="*60)

    # Step 1: Temporarily enable db.create_all() in app/__init__.py
    print("\n[1] Temporarily enabling db.create_all()...")
    init_file = 'app/__init__.py'
    with open(init_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add db.create_all() before the comment
    modified_content = content.replace(
        "    # Note: Database tables should be created via Flask-Migrate",
        "    with app.app_context():\n        db.create_all()\n\n    # Note: Database tables should be created via Flask-Migrate"
    )

    with open(init_file, 'w', encoding='utf-8') as f:
        f.write(modified_content)
    print("[OK] Enabled db.create_all()")

    # Step 2: Import app to create database
    print("\n[2] Creating database with all tables...")
    try:
        from app import create_app, db
        app = create_app()
        print("[OK] Database created")
    except Exception as e:
        print(f"[ERROR] Failed to create database: {e}")
        # Restore original content
        with open(init_file, 'w', encoding='utf-8') as f:
            f.write(content)
        return False

    # Step 3: Generate migration
    print("\n[3] Generating migration from database schema...")
    result = subprocess.run(
        ['venv/Scripts/python.exe', '-m', 'flask', 'db', 'migrate', '-m', 'Initial migration - all tables'],
        env={**os.environ, 'FLASK_APP': 'flask_app.py'},
        capture_output=True,
        text=True
    )

    if "Generating" in result.stdout:
        print("[OK] Migration file generated")
        print(result.stdout)
    else:
        print("[INFO]", result.stdout)
        print("[INFO]", result.stderr)

    # Step 4: Restore original content
    print("\n[4] Restoring app/__init__.py...")
    with open(init_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print("[OK] Restored original content")

    print("\n" + "="*60)
    print("[OK] Migration generation complete!")
    print("="*60)
    print("\nNext steps:")
    print("1. Delete the database: del instance\\cas.db")
    print("2. Apply migration: set FLASK_APP=flask_app.py && flask db upgrade")
    print("3. Load fixtures: python load_fixtures.py")
    print("="*60)

    return True

if __name__ == '__main__':
    main()
