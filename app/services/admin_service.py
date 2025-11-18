from __future__ import annotations

from app.domain import UsageStats
from app.repositories import StatsRepository


class AdminService:
    def __init__(self, stats_repo: StatsRepository) -> None:
        self._stats_repo = stats_repo

    async def get_usage_stats(self) -> UsageStats:
        return await self._stats_repo.get_usage_stats()
