"""
Script to generate sample login history data for testing
"""
from app import create_app, db
from app.users.models import User, LoginHistory
from datetime import datetime, timedelta
import random

app = create_app()

with app.app_context():
    # Get existing users
    admin = User.query.filter_by(username='admin').first()

    if not admin:
        print("Admin user not found!")
    else:
        # Create sample login history
        sample_data = [
            {
                'user': admin,
                'status': 'success',
                'failure_reason': None,
                'days_ago': 0,
                'hours_ago': 0,
                'ip': '127.0.0.1'
            },
            {
                'user': admin,
                'status': 'failed',
                'failure_reason': 'Invalid password',
                'days_ago': 0,
                'hours_ago': 2,
                'ip': '127.0.0.1'
            },
            {
                'user': admin,
                'status': 'success',
                'failure_reason': None,
                'days_ago': 1,
                'hours_ago': 0,
                'ip': '192.168.1.100'
            },
            {
                'user': None,  # Unknown user
                'username': 'hacker123',
                'fullname': 'Unknown',
                'status': 'failed',
                'failure_reason': 'Invalid username',
                'days_ago': 1,
                'hours_ago': 3,
                'ip': '203.0.113.45'
            },
            {
                'user': admin,
                'status': 'failed',
                'failure_reason': 'Account inactive',
                'days_ago': 2,
                'hours_ago': 1,
                'ip': '127.0.0.1'
            },
        ]

        for data in sample_data:
            login_time = datetime.utcnow() - timedelta(days=data['days_ago'], hours=data['hours_ago'])

            if data['user']:
                record = LoginHistory(
                    user_id=data['user'].id,
                    username=data['user'].username,
                    full_name=data['user'].full_name,
                    login_time=login_time,
                    ip_address=data['ip'],
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    status=data['status'],
                    failure_reason=data['failure_reason']
                )
            else:
                record = LoginHistory(
                    user_id=0,
                    username=data['username'],
                    full_name=data['fullname'],
                    login_time=login_time,
                    ip_address=data['ip'],
                    user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                    status=data['status'],
                    failure_reason=data['failure_reason']
                )

            db.session.add(record)

        db.session.commit()
        print(f"Successfully created {len(sample_data)} login history records!")
