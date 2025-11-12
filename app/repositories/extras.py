from __future__ import annotations

from datetime import time
from typing import Iterable

from app.domain import Extra
from app.repositories.base import BaseRepository


def _row_to_extra(row) -> Extra:
    return Extra(
        id=row["id"],
        user_id=row["user_id"],
        weekday=row["weekday"],
        name=row["name"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        location=row["location"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ExtrasRepository(BaseRepository):
    async def list_by_user_and_day(self, user_id: int, weekday: int) -> list[Extra]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM extras
                WHERE user_id = $1 AND weekday = $2
                ORDER BY start_time ASC
                """,
                user_id,
                weekday,
            )
        return [_row_to_extra(row) for row in rows]

    async def replace_day(
        self,
        user_id: int,
        weekday: int,
        extras: Iterable[dict],
    ) -> None:
        async with self.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM extras WHERE user_id = $1 AND weekday = $2",
                    user_id,
                    weekday,
                )
                if not extras:
                    return
                for payload in extras:
                    await conn.execute(
                        """
                        INSERT INTO extras (
                            user_id, weekday, name, start_time, end_time, location, notes
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        user_id,
                        weekday,
                        payload["name"],
                        payload["start_time"],
                        payload["end_time"],
                        payload.get("location"),
                        payload.get("notes"),
                    )

    async def has_overlap(
        self,
        user_id: int,
        weekday: int,
        start_time_value: time,
        end_time_value: time,
    ) -> bool:
        async with self.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM extras
                    WHERE user_id = $1 AND weekday = $2
                      AND start_time < $4
                      AND end_time > $3
                )
                """,
                user_id,
                weekday,
                start_time_value,
                end_time_value,
            )
        return bool(result)

    async def count_for_day(self, user_id: int, weekday: int) -> int:
        async with self.acquire() as conn:
            result = await conn.fetchval(
                "SELECT COUNT(*) FROM extras WHERE user_id = $1 AND weekday = $2",
                user_id,
                weekday,
            )
        return int(result or 0)
