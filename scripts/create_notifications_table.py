"""Create notifications table"""
from app import create_app, db
from app.notifications.models import Notification

app = create_app()
with app.app_context():
    # Create notifications table
    db.create_all()
    print("Notifications table created successfully!")

    # Verify table exists
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    if 'notifications' in inspector.get_table_names():
        print("✓ notifications table confirmed in database")
        columns = inspector.get_columns('notifications')
        print(f"  Columns: {[col['name'] for col in columns]}")
    else:
        print("✗ notifications table NOT found!")
