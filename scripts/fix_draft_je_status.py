"""One-off data fix for B-018: demote JEs of draft purchase bills to draft.

Run once after deploying the fix that creates draft-bill JEs as drafts.
"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(pathlib.Path(__file__).resolve().parent.parent / '.env')

from app import create_app, db
from app.purchase_bills.models import PurchaseBill
from app.journal_entries.models import JournalEntry

app = create_app('development')
with app.app_context():
    fixed = 0
    for bill in PurchaseBill.query.filter_by(status='draft').all():
        if bill.journal_entry_id:
            je = db.session.get(JournalEntry, bill.journal_entry_id)
            if je and je.status == 'posted':
                je.status = 'draft'
                je.posted_by_id = None
                je.posted_at = None
                fixed += 1
                print(f'{je.entry_number} (bill {bill.bill_number}): posted -> draft')
    db.session.commit()
    print(f'{fixed} journal entr{"y" if fixed == 1 else "ies"} demoted to draft.')
