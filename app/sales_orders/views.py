from datetime import date
from app import db
from app.utils import ph_now
from app.sales_orders.models import SalesOrder


def generate_so_number():
    """Next SO-YYYY-MM-#### for the current PH month (suffix = max existing this month + 1)."""
    today = ph_now().date()
    prefix = f"SO-{today.year:04d}-{today.month:02d}-"
    rows = (SalesOrder.query
            .filter(SalesOrder.so_number.like(prefix + '%'))
            .with_entities(SalesOrder.so_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
