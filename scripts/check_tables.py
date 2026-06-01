from app import create_app, db
from sqlalchemy import inspect

app = create_app()
with app.app_context():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print(f'Total tables: {len(tables)}')
    print('Tables:', tables)

    if 'audit_logs' in tables:
        print('\naudit_logs table exists!')
        columns = inspector.get_columns('audit_logs')
        print('Columns:', [col['name'] for col in columns])
    else:
        print('\naudit_logs table DOES NOT exist!')
