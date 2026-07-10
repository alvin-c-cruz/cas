"""Shape of the legacy Flask bookkeeping schema, shared by RIC and Philgen.

Both clients ran the same application, so one description serves both. Six
document types; `sales`, `receipts`, `disbursements` and `accounts_payable` each
have an `_x` twin (the client's parallel second set of books), while `general`
and `petty_cash` do not -- which is why the Extra branch carries no general
journal and there is no "JVX" series.

Every `_entry` table has identical columns:
    (entry_id, <parent_fk>, account_id, debit, credit, notes)
Only the parent FK column name varies, which is the whole reason this table
exists rather than being inferred.

Schema drift between the two clients is confined to header columns RIC and
Philgen do not share (`date_posted` / `check_date`), so headers are always read
with an explicit column list -- never `SELECT *`.
"""
from dataclasses import dataclass

CORP = 'CORP'
EXTRA = 'EXTRA'


@dataclass(frozen=True)
class Book:
    """One legacy document type, and where its rows land in CAS."""

    header_table: str
    entry_table: str
    entry_fk: str
    number_column: str
    prefix: str
    branch_code: str
    counterparty_column: str = None   # 'customer_id' | 'vendor_id' | None
    counterparty_table: str = None    # 'customers'   | 'vendors'    | None
    counterparty_name: str = None     # display column on that table

    @property
    def is_extra_book(self):
        return self.branch_code == EXTRA


_CUSTOMER = ('customer_id', 'customers', 'customer_name')
_VENDOR = ('vendor_id', 'vendors', 'vendor_name')


BOOKS = (
    Book('sales', 'sales_entry', 'sales_id',
         'sales_number', 'SJ', CORP, *_CUSTOMER),
    Book('sales_x', 'sales_entry_x', 'sales_x_id',
         'sales_number', 'SJX', EXTRA, *_CUSTOMER),

    Book('receipts', 'receipts_entry', 'receipt_id',
         'receipt_number', 'CRJ', CORP, *_CUSTOMER),
    Book('receipts_x', 'receipts_entry_x', 'receipt_x_id',
         'receipt_number', 'CRJX', EXTRA, *_CUSTOMER),

    Book('disbursements', 'disbursements_entry', 'disbursement_id',
         'disbursement_number', 'CDJ', CORP, *_VENDOR),
    Book('disbursements_x', 'disbursements_entry_x', 'disbursement_x_id',
         'disbursement_number', 'CDJX', EXTRA, *_VENDOR),

    Book('accounts_payable', 'accounts_payable_entry', 'accounts_payable_id',
         'accounts_payable_number', 'PJ', CORP, *_VENDOR),
    Book('accounts_payable_x', 'accounts_payable_entry_x', 'accounts_payable_x_id',
         'accounts_payable_number', 'PJX', EXTRA, *_VENDOR),

    # No `_x` twin for either of these.
    Book('general', 'general_entry', 'general_id',
         'general_number', 'JV', CORP),
    Book('petty_cash', 'petty_cash_entry', 'petty_cash_id',
         'pcv_number', 'PCV', CORP, *_VENDOR),
)


def book_by_prefix(prefix):
    for book in BOOKS:
        if book.prefix == prefix:
            return book
    raise KeyError(prefix)
