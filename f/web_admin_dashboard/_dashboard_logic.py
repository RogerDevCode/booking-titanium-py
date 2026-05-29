from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._dashboard_models import AdminDashboardResult, InputSchema


async def fetch_dashboard_stats(db: DBClient, input_data: InputSchema) -> AdminDashboardResult:
    # 1. Verify Admin
    admin_rows = await db.fetch(
        "SELECT role FROM users WHERE user_id = $1::uuid AND is_active = true LIMIT 1", input_data.admin_user_id
    )
    if not admin_rows or str(admin_rows[0]["role"]) != "admin":
        raise RuntimeError("Forbidden: admin access required")

    # 2. Main Stats
    stats_rows = await db.fetch(
        """
        SELECT
          (SELECT COUNT(*) FROM users) AS total_users,
          (SELECT COUNT(*) FROM bookings WHERE status NOT IN ('cancelled', 'rescheduled')) AS total_bookings,
          (SELECT COALESCE(SUM(s.price_cents), 0)
           FROM bookings b
           INNER JOIN services s ON b.service_id = s.service_id
           WHERE b.status = 'completed') AS total_revenue_cents,
          (SELECT COUNT(*) FROM providers WHERE is_active = true) AS active_providers,
          (SELECT COUNT(*) FROM bookings WHERE status = 'pending') AS pending_bookings
        """
    )

    if not stats_rows:
        raise RuntimeError("Failed to fetch dashboard stats")

    s = stats_rows[0]

    # 3. No-Show Rate
    ns_rows = await db.fetch(
        """
        SELECT
          COUNT(*) FILTER (WHERE status = 'no_show') AS no_show_count,
          COUNT(*) FILTER (WHERE status IN ('completed', 'no_show')) AS total_processed
        FROM bookings
        """
    )

    no_show_rate = "0.0"
    if ns_rows:
        ns = ns_rows[0]
        count = int(cast("Any", ns["no_show_count"]))
        total = int(cast("Any", ns["total_processed"]))
        if total > 0:
            no_show_rate = f"{(count / total * 100):.1f}"

    res: AdminDashboardResult = {
        "total_users": int(cast("Any", s["total_users"])),
        "total_bookings": int(cast("Any", s["total_bookings"])),
        "total_revenue_cents": int(cast("Any", s["total_revenue_cents"])),
        "no_show_rate": no_show_rate,
        "active_providers": int(cast("Any", s["active_providers"])),
        "pending_bookings": int(cast("Any", s["pending_bookings"])),
    }
    return res
