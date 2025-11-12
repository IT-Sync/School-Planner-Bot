from __future__ import annotations

from pathlib import Path
from typing import Optional

import asyncpg

from app.config import Settings


class Database:
    _BASE_DIR = Path(__file__).resolve().parents[2]

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database pool is not initialized")
        return self._pool

    async def connect(self) -> None:
        if self._pool is not None:
            return

        self._pool = await asyncpg.create_pool(
            host=self._settings.database_host,
            port=self._settings.database_port,
            user=self._settings.database_user,
            password=self._settings.database_password,
            database=self._settings.database_name,
            min_size=1,
            max_size=10,
        )
        await self._run_migrations()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _run_migrations(self) -> None:
        sql_file = self._BASE_DIR / "migrations" / "0001_init.sql"
        if not sql_file.exists():
            return

        sql = sql_file.read_text(encoding="utf-8")
        async with self.pool.acquire() as conn:
            await conn.execute(sql)
