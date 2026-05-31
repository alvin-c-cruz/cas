"""
Script to add multi-branch support to the database
"""
from app import create_app, db
from app.branches.models import Branch
from app.users.models import User

app = create_app()

with app.app_context():
    # Create branches table
    db.create_all()
    print("Branches table created successfully!")

    # Check if any branches exist
    if Branch.query.count() == 0:
        # Create a default branch
        main_branch = Branch(
            code='MAIN',
            name='Main Office',
            address='Main Office Address',
            phone='',
            email='',
            is_active=True
        )
        db.session.add(main_branch)
        db.session.commit()
        print(f"Default branch '{main_branch.name}' created successfully!")
    else:
        print(f"{Branch.query.count()} branch(es) already exist in the database.")

    print("\nMulti-branch support added successfully!")
    print("\nNext steps:")
    print("1. Restart the Flask application")
    print("2. Log in as admin")
    print("3. Go to Branch Management to create and manage branches")
    print("4. Assign accountants and staff to branches")
