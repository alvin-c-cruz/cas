"""
Recreate Database Using Flask-Migrate

This script deletes the existing database and recreates it using
Flask-Migrate migrations, then loads default fixtures.

This is the RECOMMENDED way to reset the database as it uses
proper migration versioning.

Usage:
    python recreate_db_with_migrations.py
"""
import os
import sys
import subprocess


def run_command(cmd, description):
    """Run a shell command and display output."""
    print(f"\n→ {description}...")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                print(f"  {line}")

    if result.returncode != 0:
        print(f"  ✗ Command failed!")
        if result.stderr:
            print(f"  Error: {result.stderr}")
        return False

    return True


def recreate_database_with_migrations():
    """Recreate database using Flask-Migrate."""
    print("\n" + "="*60)
    print("Recreate Database Using Flask-Migrate")
    print("="*60)

    # Warning
    print("\n⚠  WARNING: This will DELETE ALL DATA in the database!")
    print("⚠  The database will be recreated from scratch using migrations.")

    # Confirm
    response = input("\nType 'DELETE' to confirm: ").strip()
    if response != 'DELETE':
        print("\n✗ Operation cancelled.")
        return False

    # Check if database exists
    db_path = 'instance/cas.db'
    if os.path.exists(db_path):
        print(f"\n→ Deleting existing database...")
        try:
            os.remove(db_path)
            print(f"  ✓ Deleted {db_path}")
        except Exception as e:
            print(f"  ✗ Error deleting database: {e}")
            return False
    else:
        print(f"\n  ℹ No existing database found at {db_path}")

    # Set environment variable
    os.environ['FLASK_APP'] = 'flask_app.py'

    # Run migrations to create tables
    print("\n" + "="*60)
    print("Running Flask-Migrate to Create Tables")
    print("="*60)

    if not run_command(
        'set FLASK_APP=flask_app.py && venv\\Scripts\\flask.exe db upgrade',
        "Applying migrations to create database schema"
    ):
        print("\n✗ Migration failed!")
        return False

    # Load fixtures
    print("\n" + "="*60)
    print("Loading Default Fixtures")
    print("="*60)

    from app import create_app
    from app.fixtures import load_all_fixtures

    app = create_app()
    with app.app_context():
        load_all_fixtures()

    # Success message
    print("\n" + "="*60)
    print("✓ Database Successfully Recreated!")
    print("="*60)

    print("\nDatabase recreated with:")
    print("  • All tables from migrations")
    print("  • Default admin user (admin/admin123)")
    print("  • Sample chart of accounts")
    print("  • Default main branch")
    print("  • Default application settings")

    print("\n" + "="*60)
    print("Next Steps:")
    print("="*60)
    print("\n1. Start the application:")
    print("   python flask_app.py")
    print("\n2. Log in with:")
    print("   Username: admin")
    print("   Password: admin123")
    print("\n3. CHANGE THE ADMIN PASSWORD!")
    print("\n" + "="*60 + "\n")

    return True


if __name__ == '__main__':
    try:
        success = recreate_database_with_migrations()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n✗ Operation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
