from app import create_app, db
from app.audit.models import AuditLog

app = create_app()
with app.app_context():
    logs = AuditLog.query.all()
    print(f'Total audit logs: {len(logs)}')
    for log in logs[:10]:
        print(f'ID: {log.id}, Module: {log.module}, Action: {log.action}, User: {log.user_id}, Record: {log.record_identifier}, Timestamp: {log.timestamp}')
