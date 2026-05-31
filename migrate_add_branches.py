"""
Script to add multi-branch support via direct SQL migration
"""
import sqlite3
import os

# Database path
db_path = os.path.join('instance', 'cas.db')

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

# Connect to database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if branches table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='branches'")
    branches_exists = cursor.fetchone() is not None

    if not branches_exists:
        print("Creating branches table...")
        cursor.execute("""
            CREATE TABLE branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code VARCHAR(20) UNIQUE NOT NULL,
                name VARCHAR(200) NOT NULL,
                address TEXT,
                phone VARCHAR(50),
                email VARCHAR(120),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("Branches table created successfully!")

        # Create default branch
        cursor.execute("""
            INSERT INTO branches (code, name, address, is_active)
            VALUES ('MAIN', 'Main Office', 'Main Office Address', 1)
        """)
        print("Default 'Main Office' branch created!")
    else:
        print("Branches table already exists.")

    # Check if branch_id column exists in users table
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'branch_id' not in columns:
        print("Adding branch_id column to users table...")
        cursor.execute("ALTER TABLE users ADD COLUMN branch_id INTEGER")
        print("branch_id column added successfully!")
    else:
        print("branch_id column already exists in users table.")

    # Commit changes
    conn.commit()
    print("\n✅ Migration completed successfully!")
    print("\nNext steps:")
    print("1. Restart the Flask application")
    print("2. Log in as admin")
    print("3. Go to Branch Management to manage branches")
    print("4. Assign accountants and staff to branches")

except Exception as e:
    conn.rollback()
    print(f"\n❌ Error during migration: {e}")
    raise
finally:
    conn.close()
