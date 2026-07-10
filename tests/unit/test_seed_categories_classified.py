"""
Guard test: every VATCategory row seeded by load_default_vat_categories()
must carry a non-NULL transaction_nature that is a recognized PURCHASE_NATURES
member.

VATCategory.transaction_nature is nullable with no model-level default
(unlike SalesVATCategory.transaction_nature and WithholdingTax.tax_type, which
self-heal via a NOT NULL + default). A category built without an explicit
transaction_nature silently lands as NULL, which BIR 2550Q Part II reporting
renders as a visible "Unclassified" bucket. This test asserts the invariant
generally -- against every row load_default_vat_categories() creates -- not
just today's five codes, so any future row added to that function without a
transaction_nature fails the suite instead of shipping unclassified.
"""
from app.fixtures import load_default_vat_categories
from app.vat_categories.models import VATCategory, PURCHASE_NATURES
from app.accounts.models import Account


def test_load_default_vat_categories_all_rows_classified(db_session):
    # load_default_vat_categories() looks up Account code '1200' for
    # input_vat_account_id (load_sample_chart_of_accounts runs before it in
    # load_all_fixtures); create it directly rather than seeding the full COA.
    db_session.add(Account(code='1200', name='Input Tax', account_type='Asset',
                           classification='Current', normal_balance='debit',
                           is_active=True))
    db_session.commit()

    load_default_vat_categories()

    rows = VATCategory.query.all()
    assert rows, "load_default_vat_categories() created no rows"

    unclassified = [r.code for r in rows if r.transaction_nature is None]
    assert not unclassified, (
        f"VATCategory rows with NULL transaction_nature: {unclassified} -- "
        f"every seeded purchase VAT category must be classified"
    )

    bad = [(r.code, r.transaction_nature) for r in rows
           if r.transaction_nature not in PURCHASE_NATURES]
    assert not bad, (
        f"VATCategory rows with unrecognized transaction_nature: {bad} -- "
        f"must be one of {PURCHASE_NATURES}"
    )
