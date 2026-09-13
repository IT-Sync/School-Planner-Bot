from __future__ import annotations

import json
import time
from asyncio import Lock
from collections.abc import Mapping

import asyncpg
from aiogram.exceptions import DataNotDictLikeError
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey


class PostgresStorage(BaseStorage):
    """Durable aiogram FSM storage backed by the application's PostgreSQL pool."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        ttl_seconds: int,
        cleanup_interval_seconds: int = 300,
    ) -> None:
        self._pool = pool
        self._ttl_seconds = ttl_seconds
        self._cleanup_interval_seconds = cleanup_interval_seconds
        self._next_cleanup = 0.0
        self._cleanup_lock = Lock()

    async def close(self) -> None:
        # The Database instance owns the shared pool lifecycle.
        pass

    async def cleanup_expired(self) -> None:
        await self._pool.execute("DELETE FROM bot_fsm_storage WHERE expires_at <= now()")
        self._next_cleanup = time.monotonic() + self._cleanup_interval_seconds

    async def _maybe_cleanup(self) -> None:
        if time.monotonic() >= self._next_cleanup:
            async with self._cleanup_lock:
                if time.monotonic() >= self._next_cleanup:
                    await self.cleanup_expired()

    @staticmethod
    def _key_args(key: StorageKey) -> tuple[int, int, int, int | None, str | None, str]:
        return (
            key.bot_id,
            key.chat_id,
            key.user_id,
            key.thread_id,
            key.business_connection_id,
            key.destiny,
        )

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        await self._maybe_cleanup()
        value = state.state if isinstance(state, State) else state
        args = self._key_args(key)
        if value is None:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    """
                    UPDATE bot_fsm_storage
                    SET state = NULL,
                        updated_at = now(),
                        expires_at = now() + make_interval(secs => $7)
                    WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3
                      AND thread_id IS NOT DISTINCT FROM $4
                      AND business_connection_id IS NOT DISTINCT FROM $5
                      AND destiny = $6 AND expires_at > now()
                    """,
                    *args,
                    self._ttl_seconds,
                )
                await conn.execute(
                    """
                    DELETE FROM bot_fsm_storage
                    WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3
                      AND thread_id IS NOT DISTINCT FROM $4
                      AND business_connection_id IS NOT DISTINCT FROM $5
                      AND destiny = $6 AND state IS NULL AND data = '{}'::jsonb
                    """,
                    *args,
                )
            return
        await self._pool.execute(
            """
            INSERT INTO bot_fsm_storage (
                bot_id, chat_id, user_id, thread_id, business_connection_id,
                destiny, state, expires_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, now() + make_interval(secs => $8))
            ON CONFLICT ON CONSTRAINT bot_fsm_storage_key DO UPDATE
            SET state = EXCLUDED.state,
                data = CASE
                    WHEN bot_fsm_storage.expires_at <= now() THEN '{}'::jsonb
                    ELSE bot_fsm_storage.data
                END,
                updated_at = now(),
                expires_at = EXCLUDED.expires_at
            """,
            *args,
            value,
            self._ttl_seconds,
        )

    async def get_state(self, key: StorageKey) -> str | None:
        await self._maybe_cleanup()
        return await self._pool.fetchval(
            """
            SELECT state FROM bot_fsm_storage
            WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3
              AND thread_id IS NOT DISTINCT FROM $4
              AND business_connection_id IS NOT DISTINCT FROM $5
              AND destiny = $6 AND expires_at > now()
            """,
            *self._key_args(key),
        )

    async def set_data(self, key: StorageKey, data: Mapping[str, object]) -> None:
        if not isinstance(data, dict):
            raise DataNotDictLikeError(
                f"Data must be a dict or dict-like object, got {type(data).__name__}"
            )
        encoded = json.dumps(data, ensure_ascii=False)
        await self._maybe_cleanup()
        args = self._key_args(key)
        if not data:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    """
                    UPDATE bot_fsm_storage
                    SET data = '{}'::jsonb,
                        updated_at = now(),
                        expires_at = now() + make_interval(secs => $7)
                    WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3
                      AND thread_id IS NOT DISTINCT FROM $4
                      AND business_connection_id IS NOT DISTINCT FROM $5
                      AND destiny = $6 AND expires_at > now()
                    """,
                    *args,
                    self._ttl_seconds,
                )
                await conn.execute(
                    """
                    DELETE FROM bot_fsm_storage
                    WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3
                      AND thread_id IS NOT DISTINCT FROM $4
                      AND business_connection_id IS NOT DISTINCT FROM $5
                      AND destiny = $6 AND state IS NULL AND data = '{}'::jsonb
                    """,
                    *args,
                )
            return
        await self._pool.execute(
            """
            INSERT INTO bot_fsm_storage (
                bot_id, chat_id, user_id, thread_id, business_connection_id,
                destiny, data, expires_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, now() + make_interval(secs => $8))
            ON CONFLICT ON CONSTRAINT bot_fsm_storage_key DO UPDATE
            SET data = EXCLUDED.data,
                state = CASE
                    WHEN bot_fsm_storage.expires_at <= now() THEN NULL
                    ELSE bot_fsm_storage.state
                END,
                updated_at = now(),
                expires_at = EXCLUDED.expires_at
            """,
            *args,
            encoded,
            self._ttl_seconds,
        )

    async def get_data(self, key: StorageKey) -> dict[str, object]:
        await self._maybe_cleanup()
        encoded = await self._pool.fetchval(
            """
            SELECT data::text FROM bot_fsm_storage
            WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3
              AND thread_id IS NOT DISTINCT FROM $4
              AND business_connection_id IS NOT DISTINCT FROM $5
              AND destiny = $6 AND expires_at > now()
            """,
            *self._key_args(key),
        )
        return json.loads(encoded) if encoded is not None else {}

    async def update_data(self, key: StorageKey, data: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(data, dict):
            raise DataNotDictLikeError(
                f"Data must be a dict or dict-like object, got {type(data).__name__}"
            )
        encoded = json.dumps(data, ensure_ascii=False)
        await self._maybe_cleanup()
        result = await self._pool.fetchval(
            """
            INSERT INTO bot_fsm_storage (
                bot_id, chat_id, user_id, thread_id, business_connection_id,
                destiny, data, expires_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, now() + make_interval(secs => $8))
            ON CONFLICT ON CONSTRAINT bot_fsm_storage_key DO UPDATE
            SET data = CASE
                    WHEN bot_fsm_storage.expires_at <= now() THEN '{}'::jsonb
                    ELSE bot_fsm_storage.data
                END || EXCLUDED.data,
                state = CASE
                    WHEN bot_fsm_storage.expires_at <= now() THEN NULL
                    ELSE bot_fsm_storage.state
                END,
                updated_at = now(),
                expires_at = EXCLUDED.expires_at
            RETURNING data::text
            """,
            *self._key_args(key),
            encoded,
            self._ttl_seconds,
        )
        return json.loads(result)
