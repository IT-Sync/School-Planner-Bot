from __future__ import annotations

import secrets

from app.domain import ShareScope, ShareToken
from app.repositories.base import BaseRepository


def _row_to_share_token(row) -> ShareToken:
    return ShareToken(
        token=row["token"],
        owner_id=row["owner_id"],
        scope=ShareScope(row["scope"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


class ShareTokenRepository(BaseRepository):
    async def create(self, owner_id: int, scope: ShareScope) -> ShareToken:
        token = secrets.token_urlsafe(8)
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO share_tokens (token, owner_id, scope, expires_at)
                VALUES ($1, $2, $3, now() + interval '1 day')
                RETURNING token, owner_id, scope, created_at, expires_at
                """,
                token,
                owner_id,
                scope.value,
            )
        return _row_to_share_token(row)

    async def get(self, token: str) -> ShareToken | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT token, owner_id, scope, created_at, expires_at
                FROM share_tokens
                WHERE token = $1 AND expires_at > now()
                """,
                token,
            )
        if not row:
            return None
        return _row_to_share_token(row)
