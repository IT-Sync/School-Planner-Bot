from __future__ import annotations

from datetime import datetime

from app.domain import User
from app.repositories.base import BaseRepository


def _row_to_user(row) -> User:
    return User(
        id=row["id"],
        timezone=row["timezone"],
        lang=row["lang"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class UserRepository(BaseRepository):
    async def get(self, user_id: int) -> User | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1",
                user_id,
            )
        return _row_to_user(row) if row else None

    async def get_or_create(self, user_id: int) -> User:
        async with self.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            if row:
                return _row_to_user(row)

            row = await conn.fetchrow(
                """
                INSERT INTO users (id)
                VALUES ($1)
                ON CONFLICT (id) DO UPDATE
                SET updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                user_id,
            )
        return _row_to_user(row)

    async def update_profile(self, user: User) -> User:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE users
                SET timezone = $2,
                    lang = $3,
                    updated_at = $4
                WHERE id = $1
                RETURNING *
                """,
                user.id,
                user.timezone,
                user.lang,
                datetime.utcnow(),
            )
        if row is None:
            raise ValueError("User not found")
        return _row_to_user(row)
