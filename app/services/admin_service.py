from __future__ import annotations

from app.domain import AdminUserLessonStat, UsageStats
from app.repositories import StatsRepository


class AdminService:
    def __init__(self, stats_repo: StatsRepository) -> None:
        self._stats_repo = stats_repo

    async def get_usage_stats(self) -> UsageStats:
        return await self._stats_repo.get_usage_stats()

    async def list_users_with_lesson_counts(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AdminUserLessonStat]:
        return await self._stats_repo.list_users_with_lesson_counts(limit=limit, offset=offset)

    async def user_exists(self, user_id: int) -> bool:
        return await self._stats_repo.user_exists(user_id)
