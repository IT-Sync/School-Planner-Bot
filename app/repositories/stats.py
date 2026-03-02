from __future__ import annotations

from app.domain import AdminUserLessonStat, UsageStats
from app.repositories.base import BaseRepository


def _row_to_admin_user_lesson_stat(row) -> AdminUserLessonStat:
    return AdminUserLessonStat(
        user_id=row["user_id"],
        lessons_count=int(row["lessons_count"] or 0),
        extras_count=int(row["extras_count"] or 0),
    )


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
                    (
                        SELECT COUNT(DISTINCT user_id)
                        FROM (
                            SELECT user_id FROM schedule WHERE updated_at >= now() - interval '1 day'
                            UNION ALL
                            SELECT user_id FROM extras WHERE updated_at >= now() - interval '1 day'
                        ) AS combined
                    ) AS active_users_day,
                    (
                        SELECT COUNT(DISTINCT user_id)
                        FROM (
                            SELECT user_id FROM schedule WHERE updated_at >= now() - interval '7 days'
                            UNION ALL
                            SELECT user_id FROM extras WHERE updated_at >= now() - interval '7 days'
                        ) AS combined
                    ) AS active_users_week,
                    (SELECT COUNT(DISTINCT user_id) FROM schedule) AS users_with_lessons,
                    (SELECT COUNT(DISTINCT user_id) FROM extras) AS users_with_extras,
                    (SELECT COUNT(*) FROM schedule) AS lessons_total,
                    (SELECT COUNT(*) FROM extras) AS extras_total,
                    (
                        SELECT COALESCE(AVG(item_count), 0)
                        FROM (
                            SELECT user_id, COUNT(*)::float AS item_count
                            FROM schedule
                            GROUP BY user_id
                        ) AS per_user
                    ) AS avg_lessons_per_active_user,
                    (
                        SELECT COALESCE(AVG(item_count), 0)
                        FROM (
                            SELECT user_id, COUNT(*)::float AS item_count
                            FROM extras
                            GROUP BY user_id
                        ) AS per_user
                    ) AS avg_extras_per_active_user,
                    (
                        SELECT COALESCE(AVG(item_count), 0)
                        FROM (
                            SELECT user_id, COUNT(*)::float AS item_count
                            FROM (
                                SELECT user_id FROM schedule
                                UNION ALL
                                SELECT user_id FROM extras
                            ) AS all_entries
                            GROUP BY user_id
                        ) AS per_user
                    ) AS avg_total_entries_per_active_user,
                    (SELECT COUNT(*) FROM share_tokens) AS share_links_total,
                    (SELECT COUNT(*) FROM share_tokens WHERE created_at >= now() - interval '1 day') AS share_links_day,
                    (SELECT COUNT(*) FROM share_tokens WHERE created_at >= now() - interval '7 days') AS share_links_week,
                    (SELECT COUNT(*) FROM share_tokens WHERE expires_at > now()) AS active_share_links
                """
            )
        return UsageStats(
            total_users=int(row["total_users"] or 0),
            new_users_day=int(row["new_users_day"] or 0),
            new_users_week=int(row["new_users_week"] or 0),
            active_users=int(row["active_users"] or 0),
            active_users_day=int(row["active_users_day"] or 0),
            active_users_week=int(row["active_users_week"] or 0),
            users_with_lessons=int(row["users_with_lessons"] or 0),
            users_with_extras=int(row["users_with_extras"] or 0),
            lessons_total=int(row["lessons_total"] or 0),
            extras_total=int(row["extras_total"] or 0),
            avg_lessons_per_active_user=float(row["avg_lessons_per_active_user"] or 0),
            avg_extras_per_active_user=float(row["avg_extras_per_active_user"] or 0),
            avg_total_entries_per_active_user=float(row["avg_total_entries_per_active_user"] or 0),
            share_links_total=int(row["share_links_total"] or 0),
            share_links_day=int(row["share_links_day"] or 0),
            share_links_week=int(row["share_links_week"] or 0),
            active_share_links=int(row["active_share_links"] or 0),
        )

    async def list_users_with_lesson_counts(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AdminUserLessonStat]:
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(offset, 0)
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    u.id AS user_id,
                    (SELECT COUNT(*) FROM schedule s WHERE s.user_id = u.id) AS lessons_count,
                    (SELECT COUNT(*) FROM extras e WHERE e.user_id = u.id) AS extras_count
                FROM users u
                ORDER BY lessons_count DESC, extras_count DESC, u.id ASC
                LIMIT $1 OFFSET $2
                """,
                safe_limit,
                safe_offset,
            )
        return [_row_to_admin_user_lesson_stat(row) for row in rows]

    async def user_exists(self, user_id: int) -> bool:
        async with self.acquire() as conn:
            value = await conn.fetchval(
                "SELECT 1 FROM users WHERE id = $1",
                user_id,
            )
        return value is not None
