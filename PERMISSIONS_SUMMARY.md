# Permissions Summary - CAS System

## Role-Based Access Control

The CAS system now has comprehensive role-based permissions for Chart of Accounts and books.

### Chart of Accounts Permissions

| Role | View Accounts | Add Account | Edit Account | Delete Account |
|------|---------------|-------------|--------------|----------------|
| **Admin** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **Accountant** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **Staff** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Viewer** | ✅ Yes | ❌ No | ❌ No | ❌ No |

**Implementation:**
- `@accountant_or_admin_required` decorator on create, edit, delete routes
- UI buttons (Add Account, Edit, Delete) hidden for Staff and Viewer users
- Staff/Viewer attempting direct URL access get redirected with error message

---

## Book-Level Permissions

### Available Books:
1. **Journal Entries** - General journal management
2. **Accounts Receivable** - Customer invoicing
3. **Collections** - Customer payments
4. **Accounts Payable** - Vendor bills
5. **Payments** - Vendor payments

### Permission Assignment:

| Role | Book Permissions |
|------|------------------|
| **Admin** | All books (automatic) |
| **Accountant** | Assignable per user |
| **Staff** | Assignable per user |
| **Viewer** | No book access (reports only) |

**How It Works:**
- Admin/Accountant can assign specific books when creating/editing Staff or Accountant users
- Permissions stored as JSON in `users.book_permissions` column
- Use `current_user.has_book_access('journal_entries')` to check access
- Admin users bypass all book permission checks

---

## Permission Matrix

### Admin (Full Access)
- ✅ All Chart of Accounts operations
- ✅ All books (automatic access)
- ✅ User management (full access)
- ✅ System settings
- ✅ Approve/disapprove transactions

### Accountant (Professional)
- ✅ All Chart of Accounts operations
- ✅ Assignable book access (per user)
- ✅ User management (can create/edit users and assign permissions)
- ✅ Approve/disapprove transactions
- ✅ Post to general ledger

### Staff (Data Entry)
- ✅ View Chart of Accounts (read-only)
- ✅ Assignable book access (per user)
- ✅ Add/edit transactions in assigned books
- ✅ Submit for approval
- ❌ Cannot modify Chart of Accounts
- ❌ Cannot approve transactions

### Viewer (Read-Only)
- ✅ View Chart of Accounts (read-only)
- ✅ View financial reports
- ✅ View BIR reports
- ❌ Cannot access transaction books
- ❌ Cannot modify any data

---

## Use Cases

### Example 1: AR Specialist (Staff)
**Assigned Books:** Accounts Receivable, Collections

**Can Do:**
- Create customer invoices
- Record customer payments
- View Chart of Accounts for reference

**Cannot Do:**
- Add/edit accounts in Chart of Accounts
- Access AP or Payments modules
- Create journal entries

### Example 2: AP Specialist (Staff)
**Assigned Books:** Accounts Payable, Payments

**Can Do:**
- Enter vendor bills
- Process vendor payments
- View Chart of Accounts for reference

**Cannot Do:**
- Add/edit accounts in Chart of Accounts
- Access AR or Collections modules
- Create journal entries

### Example 3: Senior Accountant
**Assigned Books:** All books

**Can Do:**
- Modify Chart of Accounts
- Access all transaction modules
- Approve/disapprove transactions
- Post to general ledger

**Cannot Do:**
- Create/manage users (admin only)

### Example 4: External Auditor (Viewer)
**Assigned Books:** None

**Can Do:**
- View Chart of Accounts
- View all financial reports
- Export reports for analysis

**Cannot Do:**
- Modify any data
- Access transaction entry screens

---

## Implementation Details

### Backend

**Permission Decorator:**
```python
@accountant_or_admin_required
def create():
    # Only Accountant or Admin can access
```

**Check Book Access:**
```python
if not current_user.has_book_access('journal_entries'):
    flash('You do not have permission to access Journal Entries.', 'error')
    return redirect(url_for('dashboard.index'))
```

### Frontend

**Hide Buttons:**
```jinja2
{% if current_user.role in ['accountant', 'admin'] %}
    <a href="{{ url_for('accounts.create') }}" class="btn btn-primary">
        + Add Account
    </a>
{% endif %}
```

**Book Permissions Form:**
- Automatically shown for Staff/Accountant roles
- Hidden for Admin (has all access) and Viewer (no access)
- JavaScript toggles visibility based on role selection

---

## Database Schema

### users.book_permissions
**Type:** TEXT (JSON)

**Example:**
```json
{
  "journal_entries": true,
  "accounts_receivable": false,
  "collections": true,
  "accounts_payable": false,
  "payments": true
}
```

---

## Security Notes

1. **Defense in Depth:**
   - Backend decorators enforce permissions
   - UI hides unauthorized actions
   - Direct URL access blocked with redirect

2. **Admin Privileges:**
   - Admins bypass all permission checks
   - Always have access to all features

3. **Separation of Duties:**
   - AR and AP can be separated to different users
   - Journal Entries can be restricted to accountants only

4. **Audit Trail:**
   - All permission changes logged through user edit history
   - Created_at/Updated_at timestamps on user model

---

## Future Enhancements

- Transaction amount limits per user
- Time-based access restrictions (e.g., month-end only)
- Department-level segregation
- Custom permission groups/templates
- Detailed audit log of permission changes
