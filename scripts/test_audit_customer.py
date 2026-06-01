"""Test audit logging by creating a customer"""
from app import create_app, db
from app.customers.models import Customer
from app.audit.utils import log_create, model_to_dict
from flask_login import login_user
from app.users.models import User

app = create_app()
with app.app_context():
    # Get admin user
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        print("Admin user not found!")
        exit(1)

    print(f"Found user: {admin.username} (ID: {admin.id})")

    # Create test customer
    customer = Customer(
        code='TEST001',
        name='Test Customer for Audit',
        contact_person='John Doe',
        phone='123-456-7890',
        email='test@example.com',
        is_active=True
    )

    db.session.add(customer)
    db.session.commit()
    print(f"Created customer: {customer.code} - {customer.name} (ID: {customer.id})")

    # Try to log audit - simulating what happens in the view
    # But we need current_user context...
    # Let's check if log_audit can work without flask request context

    try:
        # Import needed for audit
        from app.audit.models import AuditLog

        # Create audit log entry directly
        audit_entry = AuditLog(
            module='customer',
            action='create',
            record_id=customer.id,
            record_identifier=f'{customer.code} - {customer.name}',
            user_id=admin.id,
            new_values='{"code": "TEST001", "name": "Test Customer for Audit"}',
            notes='Test audit log creation'
        )
        db.session.add(audit_entry)
        db.session.commit()
        print(f"Created audit log entry (ID: {audit_entry.id})")

        # Check if it's in database
        logs = AuditLog.query.all()
        print(f"\nTotal audit logs now: {len(logs)}")
        for log in logs:
            print(f"  - ID: {log.id}, Module: {log.module}, Action: {log.action}, User: {log.user_id}")

    except Exception as e:
        print(f"Error creating audit log: {e}")
        import traceback
        traceback.print_exc()
