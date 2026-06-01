"""
Load Default Fixtures

This script loads all default fixtures into the database.
Use this after running flask db upgrade.
"""
from app import create_app, db
from app.fixtures import load_all_fixtures

def main():
    print("="*60)
    print("Load Default Fixtures")
    print("="*60)

    app = create_app()
    with app.app_context():
        # First, create all tables (in case migration didn't)
        print("\n[1] Ensuring all tables exist...")
        db.create_all()
        print("[OK] Tables verified/created")

        # Load fixtures
        print("\n[2] Loading default fixtures...")
        load_all_fixtures()

    print("\n[OK] Fixtures loaded successfully!")
    print("="*60)

if __name__ == '__main__':
    main()
