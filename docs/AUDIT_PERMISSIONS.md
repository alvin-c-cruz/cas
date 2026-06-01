# Audit Trail & User Log Permissions

This document describes the permissions for viewing audit trails and user logs in the CAS application.

## Current Implementation

### Login History (Implemented)
**Route:** `/login-history`
**Access:** Admin and Accountant roles only
**Features:**
- View all login attempts (successful and failed)
- See login timestamps, IP addresses, and user agents
- Track failure reasons (invalid username, invalid password, account inactive)
- Historical record of all user authentication activity

**What is tracked:**
- Username and full name
- Login time (date and time)
- IP address
- User agent (browser/device info)
- Status (success or failed)
- Failure reason (if applicable)

### User Management (Implemented)
**Route:** `/users`
**Access:** Admin and Accountant roles only
**Features:**
- View all users (accountants cannot see admin users)
- Create new users (both roles)
- Edit users (accountants cannot edit admin users)
- Activate/deactivate users
- Manage user roles and book permissions
- Delete users (admin only)

**Last Login Tracking:**
- Each user record shows their last login timestamp
- Updated automatically on successful login

### Audit Log (Planned)
**Route:** `/audit-log` (not yet implemented)
**Access:** Admin and Accountant roles only
**Planned Features:**
- Track all data modifications (create, update, delete)
- Record user actions on:
  - Chart of Accounts changes
  - Journal entries
  - Accounts receivable/payable transactions
  - Collections and payments
  - User account changes
- Show timestamp, user, action type, and affected records
- Filter by date range, user, module, or action type

## Permission Matrix

| Feature | Admin | Accountant | Staff | Viewer |
|---------|-------|------------|-------|--------|
| View Login History | ✅ Yes | ✅ Yes | ❌ No | ❌ No |
| View User Management | ✅ Yes | ✅ Yes | ❌ No | ❌ No |
| View All Users | ✅ Yes | ⚠️ Yes (except admins) | ❌ No | ❌ No |
| Create Users | ✅ Yes | ✅ Yes | ❌ No | ❌ No |
| Edit Users | ✅ Yes | ⚠️ Yes (except admins) | ❌ No | ❌ No |
| Delete Users | ✅ Yes | ❌ No | ❌ No | ❌ No |
| View Audit Log | ✅ Yes (planned) | ✅ Yes (planned) | ❌ No | ❌ No |

## Technical Implementation

### Decorator Used
```python
@admin_required
```

This decorator allows both **admin** and **accountant** roles to access the protected routes.

**Code location:** `app/users/views.py:13-21`

```python
def admin_required(f):
    """Decorator to require admin or accountant role for user management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'accountant']:
            flash('You need administrator or accountant privileges to access User Management.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function
```

### Routes Protected

1. **Login History**
   - Route: `@users_bp.route('/login-history')`
   - Decorator: `@login_required`, `@admin_required`
   - File: `app/users/views.py:126-133`

2. **User Management List**
   - Route: `@users_bp.route('/users')`
   - Decorator: `@login_required`, `@admin_required`
   - File: `app/users/views.py:148-157`

3. **Create User**
   - Route: `@users_bp.route('/users/create')`
   - Decorator: `@login_required`, `@admin_required`
   - File: `app/users/views.py:160-168`

4. **Edit User**
   - Route: `@users_bp.route('/users/<int:id>/edit')`
   - Decorator: `@login_required`, `@admin_required`
   - Additional check: Accountants cannot edit admin users
   - File: `app/users/views.py:171-226`

5. **Delete User**
   - Route: `@users_bp.route('/users/<int:id>/delete')`
   - Decorator: `@login_required`, `@admin_required`
   - Additional check: Only admin role can delete (accountants blocked)
   - File: `app/users/views.py:229-257`

## Navigation Visibility

The sidebar navigation shows audit-related links only to admin and accountant users:

```jinja2
{% if current_user.is_authenticated and current_user.role in ['admin', 'accountant'] %}
    <a href="{{ url_for('users.list_users') }}">User Management</a>
    <a href="{{ url_for('users.login_history') }}">Login History</a>
    <a href="#">Audit Log (Coming Soon)</a>
{% endif %}
```

**File location:** `app/templates/base.html:796-810`

## Security Notes

1. **Role-based Access Control (RBAC)** ensures only authorized roles can access audit features
2. **Login tracking** captures IP addresses and user agents for security monitoring
3. **Failed login attempts** are logged to detect potential security threats
4. **Accountant restrictions** prevent accountants from viewing or modifying admin accounts
5. **Delete restrictions** ensure only admin users can permanently remove user accounts

## Future Enhancements

1. **Audit Log Implementation**
   - Create AuditLog model to track all database changes
   - Implement audit trail for Chart of Accounts
   - Track journal entry modifications
   - Record transaction approvals/rejections

2. **Export Functionality**
   - Export login history to Excel/PDF
   - Generate security audit reports
   - Schedule periodic audit summaries

3. **Alerts & Notifications**
   - Alert on multiple failed login attempts
   - Notify admins of suspicious activity
   - Email reports to accountants

4. **Advanced Filtering**
   - Filter login history by date range
   - Filter by user, status, or IP address
   - Search functionality for audit logs
