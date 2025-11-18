from __future__ import annotations

from app.domain import UsageStats
from app.repositories.base import BaseRepository


class StatsRepository(BaseRepository):
    async def get_usage_stats(self) -> UsageStats:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS total_users,
                    (SELECT COUNT(*) FROM users WHERE created_at >= now() - interval '1 day') AS new_users_day,
                    (SELECT COUNT(*) FROM users WHERE created_at >= now() - interval '7 days') AS new_users_week,
                    (
                        SELECT COUNT(DISTINCT user_id)
                        FROM (
                            SELECT user_id FROM schedule
                            UNION ALL
                            SELECT user_id FROM extras
                        ) AS combined
                    ) AS active_users,
                    (SELECT COUNT(*) FROM schedule) AS lessons_total,
                    (SELECT COUNT(*) FROM extras) AS extras_total,
                    (SELECT COUNT(*) FROM share_tokens WHERE created_at >= now() - interval '7 days') AS share_links_week
                """
            )
        return UsageStats(
            total_users=int(row["total_users"] or 0),
            new_users_day=int(row["new_users_day"] or 0),
            new_users_week=int(row["new_users_week"] or 0),
            active_users=int(row["active_users"] or 0),
            lessons_total=int(row["lessons_total"] or 0),
            extras_total=int(row["extras_total"] or 0),
            share_links_week=int(row["share_links_week"] or 0),
        )
