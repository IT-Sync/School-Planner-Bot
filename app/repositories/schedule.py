from __future__ import annotations

from datetime import time
from typing import Iterable

from app.domain import Lesson
from app.repositories.base import BaseRepository


def _row_to_lesson(row) -> Lesson:
    return Lesson(
        id=row["id"],
        user_id=row["user_id"],
        weekday=row["weekday"],
        subject=row["subject"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        location=row["location"],
        teacher=row["teacher"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ScheduleRepository(BaseRepository):
    async def list_by_user_and_day(self, user_id: int, weekday: int) -> list[Lesson]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM schedule
                WHERE user_id = $1 AND weekday = $2
                ORDER BY start_time ASC
                """,
                user_id,
                weekday,
            )
        return [_row_to_lesson(row) for row in rows]

    async def replace_day(
        self,
        user_id: int,
        weekday: int,
        lessons: Iterable[dict],
    ) -> None:
        async with self.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM schedule WHERE user_id = $1 AND weekday = $2",
                    user_id,
                    weekday,
                )
                if not lessons:
                    return
                for payload in lessons:
                    await conn.execute(
                        """
                        INSERT INTO schedule (
                            user_id, weekday, subject, start_time, end_time, location, teacher
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        user_id,
                        weekday,
                        payload["subject"],
                        payload["start_time"],
                        payload["end_time"],
                        payload.get("location"),
                        payload.get("teacher"),
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
                    SELECT 1 FROM schedule
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
                "SELECT COUNT(*) FROM schedule WHERE user_id = $1 AND weekday = $2",
                user_id,
                weekday,
            )
        return int(result or 0)

    async def update_subject(self, lesson_id: int, user_id: int, subject: str) -> bool:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE schedule
                SET subject = $3,
                    updated_at = now()
                WHERE id = $1 AND user_id = $2
                RETURNING id
                """,
                lesson_id,
                user_id,
                subject,
            )
        return row is not None

    async def delete_entry(self, lesson_id: int, user_id: int) -> bool:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM schedule WHERE id = $1 AND user_id = $2 RETURNING id",
                lesson_id,
                user_id,
            )
        return row is not None
