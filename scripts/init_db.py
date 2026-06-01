"""
Database Initialization Script

This script initializes a fresh database using Flask-Migrate migrations
and loads default fixtures.

Usage:
    python init_db.py
"""
import os
import sys
from app import create_app, db
from app.fixtures import load_all_fixtures


def init_database():
    """Initialize database with migrations and fixtures."""
    app = create_app()

    with app.app_context():
        print("\n" + "="*60)
        print("CAS Database Initialization")
        print("="*60)

        # Check if database exists
        db_path = 'instance/cas.db'
        db_exists = os.path.exists(db_path)

        if db_exists:
            print(f"\n⚠ Database already exists at: {db_path}")
            print("\nOptions:")
            print("  1. Load missing fixtures only (safe)")
            print("  2. Delete and recreate database (DESTRUCTIVE)")
            print("  3. Cancel")

            choice = input("\nEnter your choice (1-3): ").strip()

            if choice == '1':
                print("\n→ Loading missing fixtures...")
                load_all_fixtures()
                print("\n✓ Database initialization complete!")

            elif choice == '2':
                confirm = input("\n⚠ This will DELETE ALL DATA! Type 'DELETE' to confirm: ")
                if confirm == 'DELETE':
                    print("\n→ Deleting existing database...")
                    try:
                        os.remove(db_path)
                        print(f"  ✓ Deleted {db_path}")
                    except Exception as e:
                        print(f"  ✗ Error deleting database: {e}")
                        return False

                    print("\n→ Creating fresh database from migrations...")
                    db.create_all()
                    print("  ✓ Tables created")

                    load_all_fixtures()
                    print("\n✓ Database recreated successfully!")
                else:
                    print("\n✗ Database recreation cancelled.")
                    return False

            else:
                print("\n✗ Cancelled.")
                return False

        else:
            print(f"\n→ No existing database found. Creating new database...")
            print(f"  Location: {db_path}\n")

            # Create tables from models
            db.create_all()
            print("  ✓ Tables created from models")

            # Load default fixtures
            load_all_fixtures()

            print("\n✓ Fresh database created successfully!")

        print("\n" + "="*60)
        print("Next Steps:")
        print("="*60)
        print("\n1. Start the application:")
        print("   python flask_app.py")
        print("\n2. Log in with default admin account:")
        print("   Username: admin")
        print("   Password: admin123")
        print("\n3. Change the admin password immediately!")
        print("\n4. To use migrations in the future:")
        print("   set FLASK_APP=flask_app.py")
        print("   flask db migrate -m \"description\"")
        print("   flask db upgrade")
        print("\n" + "="*60 + "\n")

        return True


if __name__ == '__main__':
    try:
        success = init_database()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Error during database initialization: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
