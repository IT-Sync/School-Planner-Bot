from __future__ import annotations

import asyncpg


class BaseRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def acquire(self):
        return self._pool.acquire()
