"""
Migration script to add book_permissions column to users table
"""
from app import create_app, db

app = create_app()

with app.app_context():
    # Add book_permissions column to users table
    with db.engine.connect() as conn:
        try:
            # Check if column exists
            result = conn.execute(db.text("PRAGMA table_info(users)"))
            columns = [row[1] for row in result.fetchall()]

            if 'book_permissions' not in columns:
                print("Adding book_permissions column to users table...")
                conn.execute(db.text("ALTER TABLE users ADD COLUMN book_permissions TEXT DEFAULT '{}'"))
                conn.commit()
                print("[OK] book_permissions column added successfully!")
            else:
                print("[INFO] book_permissions column already exists.")

            # Update existing users to have empty permissions
            conn.execute(db.text("UPDATE users SET book_permissions = '{}' WHERE book_permissions IS NULL"))
            conn.commit()
            print("[OK] Updated existing users with default permissions.")

            print("\nMigration completed successfully!")

        except Exception as e:
            print(f"[ERROR] Migration failed: {str(e)}")
            conn.rollback()
