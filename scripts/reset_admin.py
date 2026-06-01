from app import create_app, db
from app.users.models import User

app = create_app()

with app.app_context():
    admin = User.query.filter_by(username='admin').first()

    if admin:
        admin.set_password('admin123')
        admin.is_active = True
        db.session.commit()
        print("Admin password reset successfully!")
        print("Username: admin")
        print("Password: admin123")
        print(f"Is Active: {admin.is_active}")
    else:
        # Create admin if doesn't exist
        admin = User(
            username='admin',
            email='admin@cas.local',
            full_name='System Administrator',
            role='admin',
            is_active=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Admin user created successfully!")
        print("Username: admin")
        print("Password: admin123")
