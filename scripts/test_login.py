from app import create_app, db
from app.users.models import User

app = create_app()

with app.app_context():
    # Test login
    username = 'admin'
    password = 'admin123'

    print(f"Attempting to login with username: {username}")

    user = User.query.filter_by(username=username).first()

    if user is None:
        print("ERROR: User not found!")
    else:
        print(f"User found: {user.username}")
        print(f"User email: {user.email}")
        print(f"User is_active: {user.is_active}")
        print(f"User role: {user.role}")

        password_check = user.check_password(password)
        print(f"Password check result: {password_check}")

        if password_check and user.is_active:
            print("SUCCESS: Login would succeed!")
        else:
            if not password_check:
                print("ERROR: Password is incorrect")
            if not user.is_active:
                print("ERROR: User is not active")
