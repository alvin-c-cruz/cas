"""SA-YYYY-MM-#### numbering, mirroring petty_cash.numbering._next_number."""
from app.utils import ph_now
from app.stock_adjustments.models import StockAdjustment


def generate_sa_number():
    today = ph_now().date()
    prefix = f"SA-{today.year:04d}-{today.month:02d}-"
    rows = (StockAdjustment.query.filter(StockAdjustment.sa_number.like(prefix + '%'))
            .with_entities(StockAdjustment.sa_number).all())
    nums = [int(n.rsplit('-', 1)[-1]) for (n,) in rows if n.rsplit('-', 1)[-1].isdigit()]
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
