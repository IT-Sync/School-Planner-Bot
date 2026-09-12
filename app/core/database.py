from __future__ import annotations

import hashlib
from importlib.resources import files

import asyncpg

from app.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

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
            command_timeout=30,
            server_settings={
                "application_name": "school-planner",
                "planner.default_timezone": self._settings.default_tz,
            },
        )
        if self._settings.auto_migrate:
            await self._run_migrations()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _run_migrations(self) -> None:
        migration_files = sorted(
            (
                p
                for p in files("migrations").iterdir()
                if p.name[0].isdigit() and p.name.endswith(".sql")
            ),
            key=lambda p: p.name,
        )
        if not migration_files:
            raise RuntimeError("Migration files are missing from the application")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(731540120)")
                await conn.execute("""CREATE TABLE IF NOT EXISTS planner_migrations (
                    name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())""")
                for file in migration_files:
                    sql = file.read_text(encoding="utf-8")
                    checksum = hashlib.sha256(sql.encode()).hexdigest()
                    saved = await conn.fetchval(
                        "SELECT checksum FROM planner_migrations WHERE name=$1", file.name
                    )
                    if saved is not None:
                        if checksum != saved:
                            raise RuntimeError(f"Applied migration changed: {file.name}")
                        continue
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO planner_migrations(name,checksum) VALUES($1,$2)",
                        file.name,
                        checksum,
                    )
