"""backfill Rev 0 for pre-existing confirmed Sales Orders

Revision ID: sorev_0002
Revises: sorev_0001
Create Date: 2026-08-04

Existing confirmed SOs predate revision tracking, so their Rev 0 is
RECONSTRUCTED FROM CURRENT STATE, not captured at confirm time. For any SO that
was edited while still draft, this snapshot is not literally what was confirmed
-- so every backfilled row says so in its `reason`, and the UI shows it.
Claiming otherwise would be exactly the dishonesty this feature exists to remove.
"""
import json
from alembic import op
import sqlalchemy as sa

revision = 'sorev_0002'
down_revision = 'sorev_0001'
branch_labels = None
depends_on = None

RECONSTRUCTED = 'Rev 0 - reconstructed at upgrade, not an original capture'


def upgrade():
    conn = op.get_bind()
    orders = conn.execute(sa.text(
        "SELECT id, branch_id, so_number, status FROM sales_orders "
        "WHERE status = 'confirmed'")).fetchall()

    for so_id, branch_id, so_number, status in orders:
        exists = conn.execute(sa.text(
            "SELECT 1 FROM sales_order_revisions WHERE sales_order_id = :sid"),
            {'sid': so_id}).first()
        if exists:
            continue

        lines = conn.execute(sa.text(
            "SELECT line_number, product_id, quantity, unit_price, amount "
            "FROM sales_order_items WHERE sales_order_id = :sid "
            "ORDER BY line_number"), {'sid': so_id}).fetchall()

        snapshot = {
            'header': {'so_number': so_number, 'status': status},
            'lines': [{'line_number': ln, 'product_id': pid,
                       'quantity': str(q) if q is not None else None,
                       'unit_price': str(up) if up is not None else None,
                       'amount': str(a) if a is not None else None}
                      for ln, pid, q, up, a in lines],
        }

        conn.execute(sa.text(
            "INSERT INTO sales_order_revisions "
            "(sales_order_id, revision_number, snapshot_json, reason, "
            " amended_at, branch_id) "
            "VALUES (:sid, 0, :snap, :reason, CURRENT_TIMESTAMP, :bid)"),
            {'sid': so_id, 'snap': json.dumps(snapshot),
             'reason': RECONSTRUCTED, 'bid': branch_id})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM sales_order_revisions WHERE revision_number = 0 "
        "AND reason = :reason"), {'reason': RECONSTRUCTED})
