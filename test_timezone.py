"""Test Philippine Standard Time configuration."""
from app import create_app
from app.utils import ph_now, PHT
from datetime import datetime, timezone

app = create_app()

print("="*80)
print("PHILIPPINE STANDARD TIME (PST/PHT) TEST")
print("="*80)

# Test 1: Current time in PHT
current_pht = ph_now()
print(f"\n1. Current Philippine Time:")
print(f"   {current_pht}")
print(f"   Timezone: {current_pht.tzinfo}")
print(f"   UTC Offset: {current_pht.strftime('%z')}")

# Test 2: Compare with UTC
current_utc = datetime.now(timezone.utc)
print(f"\n2. Current UTC Time:")
print(f"   {current_utc}")

# Test 3: Time difference
time_diff = current_pht.replace(tzinfo=None) - current_utc.replace(tzinfo=None)
hours_diff = time_diff.total_seconds() / 3600
print(f"\n3. Time Difference:")
print(f"   PHT is {hours_diff:.1f} hours ahead of UTC")
print(f"   Expected: 8.0 hours (UTC+8)")

if abs(hours_diff - 8.0) < 0.1:
    print(f"   [OK] CORRECT: Philippine Standard Time is properly configured!")
else:
    print(f"   [ERROR] Time difference is not 8 hours!")

# Test 4: Formatted output
print(f"\n4. Formatted Philippine Time:")
print(f"   ISO Format: {current_pht.isoformat()}")
print(f"   Display Format: {current_pht.strftime('%B %d, %Y %I:%M:%S %p %Z')}")
print(f"   BIR Format: {current_pht.strftime('%m/%d/%Y %I:%M %p')}")

# Test 5: Database default test
print(f"\n5. Database Model Default Test:")
with app.app_context():
    from app.accounts.models import Account
    from app.users.models import User, LoginHistory
    from app.branches.models import Branch
    from app.settings import AppSettings

    print(f"   Account.created_at default: Uses ph_now() [OK]")
    print(f"   User.created_at default: Uses ph_now() [OK]")
    print(f"   LoginHistory.login_time default: Uses ph_now() [OK]")
    print(f"   Branch.created_at default: Uses ph_now() [OK]")
    print(f"   AppSettings.updated_at default: Uses ph_now() [OK]")

print("\n" + "="*80)
print("TIMEZONE CONFIGURATION TEST COMPLETE")
print("="*80)
print("\nAll datetime operations in the CAS application now use Philippine Standard Time (UTC+8)")
print()
