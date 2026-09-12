from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar

import asyncpg

# Each asyncio task has its own connection; nested repository calls participate
# in the caller's transaction instead of acquiring unrelated connections.
_transaction_connection: ContextVar[tuple[object, asyncpg.Connection] | None] = ContextVar(
    "transaction_connection", default=None
)


@asynccontextmanager
async def unit_of_work(pool, user_id: int):
    bound = _transaction_connection.get()
    if bound and bound[0] is pool:
        yield bound[1]
        return
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
            # Same profile lock as the web service; protects limits/overlaps
            # between a bot edit and a concurrent web edit.
            await conn.fetch(
                """SELECT p.id FROM profiles p
                               WHERE p.owner_id=$1 AND p.is_default FOR UPDATE OF p""",
                user_id,
            )
            token = _transaction_connection.set((pool, conn))
            try:
                yield conn
            finally:
                _transaction_connection.reset(token)


class BaseRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def acquire(self):
        bound = _transaction_connection.get()
        if bound and bound[0] is self._pool:
            yield bound[1]
        else:
            async with self._pool.acquire() as conn:
                yield conn
