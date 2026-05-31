# Book Permissions Feature

## Overview

The CAS system now supports granular book-level permissions for Staff and Accountant users. Administrators can assign specific books to each user, controlling which modules they can access.

## Available Books

1. **Journal Entries** - General journal entry management
2. **Accounts Receivable** - Customer invoicing and receivables
3. **Collections** - Payment collection from customers
4. **Accounts Payable** - Vendor bills and payables
5. **Payments** - Payment processing to vendors

## How It Works

### For Administrators

When creating or editing a **Staff** or **Accountant** user:

1. Select the user's role (Staff or Accountant)
2. The "Book Access Permissions" section will appear automatically
3. Check the boxes for the books this user should access
4. Save the user

**Note:**
- Viewer role users cannot access any transaction books (read-only reports access)
- Admin role users automatically have access to ALL books

### Permission Storage

Book permissions are stored in the `users.book_permissions` column as JSON:

```json
{
  "journal_entries": true,
  "accounts_receivable": false,
  "collections": true,
  "accounts_payable": false,
  "payments": true
}
```

### Backend Usage

**Check if user has access to a book:**

```python
from flask_login import current_user

# Check single book access
if current_user.has_book_access('journal_entries'):
    # Allow access
    pass
else:
    # Deny access
    flash('You do not have permission to access Journal Entries.', 'error')
    return redirect(url_for('dashboard.index'))
```

**Get all user permissions:**

```python
permissions = current_user.get_book_permissions()
# Returns: {'journal_entries': True, 'accounts_receivable': False, ...}
```

**Set user permissions (admin only):**

```python
user = User.query.get(user_id)
user.set_book_permissions({
    'journal_entries': True,
    'accounts_receivable': True,
    'collections': False,
    'accounts_payable': False,
    'payments': True
})
db.session.commit()
```

## Example Permission Scenarios

### Scenario 1: AR Clerk
**Role:** Staff
**Books:** Accounts Receivable, Collections
**Can:**
- Create and edit customer invoices
- Record customer payments
**Cannot:**
- Access vendor bills or payments
- Create journal entries

### Scenario 2: AP Clerk
**Role:** Staff
**Books:** Accounts Payable, Payments
**Can:**
- Enter vendor bills
- Process vendor payments
**Cannot:**
- Access customer transactions
- Create journal entries

### Scenario 3: Senior Accountant
**Role:** Accountant
**Books:** All books checked
**Can:**
- Access all transaction modules
- Approve/disapprove records
- Post to general ledger

### Scenario 4: Auditor
**Role:** Viewer
**Books:** N/A (not applicable)
**Can:**
- View financial reports only
**Cannot:**
- Access any transaction entry screens

## Implementation Notes

### Model Methods

The `User` model includes these helper methods:

- `get_book_permissions()` - Returns dict of permissions
- `set_book_permissions(dict)` - Sets permissions from dict
- `has_book_access(book_name)` - Checks access to specific book

### Form Handling

Book permissions are handled via checkboxes in the user form:
- Checkboxes are only shown for Staff and Accountant roles
- JavaScript automatically shows/hides the section based on role selection
- On edit, checkboxes are pre-populated from existing permissions

### Database

- Column: `users.book_permissions`
- Type: TEXT (stores JSON string)
- Default: `'{}'` (empty permissions)

## Future Enhancements

Consider adding:
- Department-level permissions
- Time-based access restrictions
- Transaction amount limits per user
- Audit trail of permission changes
- Bulk permission assignment
- Permission templates/presets
