# User Roles and Permissions

This document describes the different user roles in the CAS (Computerized Accounting System) and their permissions.

## Role Hierarchy

From least to most privileged:

1. **Viewer** (Read-only)
2. **Staff** (Data Entry)
3. **Accountant** (Review & Approve)
4. **Administrator** (Full Access)

---

## Role Descriptions

### 1. Viewer (viewer)
**Color Badge:** Yellow

**Description:** Read-only access to reports and financial data.

**Permissions:**
- ✅ View financial reports
- ✅ View BIR reports
- ✅ View dashboard
- ❌ Cannot add/edit transactions
- ❌ Cannot approve/disapprove records
- ❌ Cannot access user management

**Use Case:** External auditors, board members, investors who need to view financial data but not modify anything.

---

### 2. Staff (staff)
**Color Badge:** Green

**Description:** Data entry personnel who can create and edit transactions.

**Permissions:**
- ✅ View financial reports
- ✅ View BIR reports
- ✅ View dashboard
- ✅ Add transactions (journal entries, invoices, bills, payments)
- ✅ Edit their own transactions (in draft state)
- ✅ Submit transactions for approval
- ❌ Cannot approve/disapprove records
- ❌ Cannot access user management
- ❌ Cannot modify approved transactions

**Use Case:** Bookkeepers, accounting clerks, data entry staff.

---

### 3. Accountant (accountant)
**Color Badge:** Blue

**Description:** Professional accountants who can review, approve, and manage financial records.

**Permissions:**
- ✅ View financial reports
- ✅ View BIR reports
- ✅ View dashboard
- ✅ Add transactions
- ✅ Edit all transactions (including those created by others)
- ✅ **Approve/Disapprove** transactions and records
- ✅ Post to general ledger
- ✅ Close accounting periods
- ❌ Cannot access user management
- ❌ Cannot change system settings

**Use Case:** Certified Public Accountants (CPAs), accounting managers, financial controllers.

---

### 4. Administrator (admin)
**Color Badge:** Red

**Description:** System administrators with full access to all features and settings.

**Permissions:**
- ✅ **All permissions of Accountant role**
- ✅ User management (create, edit, activate/deactivate users)
- ✅ Change user roles
- ✅ Access audit logs
- ✅ System settings and configuration
- ✅ Database backup and restore
- ✅ Delete records (with proper authorization)

**Use Case:** IT administrators, business owners, system managers.

---

## Default Role for New Registrations

When users self-register through the registration page:
- **Default Role:** Viewer
- **Account Status:** Inactive (requires admin approval)

This ensures that new users have minimal access until an administrator reviews and assigns the appropriate role.

---

## Role Assignment

Only **Administrators** can:
- Assign roles to users
- Change user roles
- Activate/deactivate user accounts

---

## Workflow Example

1. **User registers** → Account created as **Viewer** (inactive)
2. **Admin reviews** → Activates account and assigns role:
   - If bookkeeper → Change to **Staff**
   - If CPA → Change to **Accountant**
   - If auditor → Keep as **Viewer**
3. **Staff** creates transactions → Submits for approval
4. **Accountant** reviews and approves → Posts to ledger
5. **Admin** manages users and system settings

---

## Future Enhancements

Consider implementing:
- Custom roles with granular permissions
- Department-based access control
- Temporary role assignments
- Role-based email notifications
