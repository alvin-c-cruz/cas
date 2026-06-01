from app import create_app, db
from app.vat_categories.models import VATCategoryChangeRequest

app = create_app()
with app.app_context():
    requests = VATCategoryChangeRequest.query.all()
    print(f'Total VAT change requests: {len(requests)}')
    for r in requests[:10]:
        print(f'ID: {r.id}, Action: {r.action}, Status: {r.status}, VAT Category ID: {r.vat_category_id}')
