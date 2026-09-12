from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, timedelta
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.planner.schemas import EventPayload, TaskPayload

EVENT_FIELDS = (
    "weekday",
    "type",
    "label",
    "start_time",
    "end_time",
    "location",
    "subtitle",
    "event_date",
)
OVERRIDE_FIELDS = ("type", "label", "start_time", "end_time", "location", "subtitle")


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def overlaps(a: dict, b: dict) -> bool:
    return a["start_time"] < b["end_time"] and a["end_time"] > b["start_time"]


def dated_entries(
    events: list[dict], exceptions: list[dict], holidays: list[dict], day: date
) -> list[dict]:
    """Resolve a calendar day without mutating weekly templates or stored exceptions."""
    exception_map = {entry["event_id"]: entry for entry in exceptions if entry["date"] == day}
    active_holidays = [h for h in holidays if h["start_date"] <= day <= h["end_date"]]
    result = []
    for original in events:
        if original.get("deleted_at") or original["weekday"] != day.isoweekday():
            continue
        if original.get("event_date") not in (None, day):
            continue
        item = dict(original)
        item.update(cancelled=False, is_override=False, occurrence_date=day)
        exception = exception_map.get(item["id"])
        if exception:
            item.update({key: exception[key] for key in OVERRIDE_FIELDS})
            item.update(
                is_override=True, base_event_id=item["id"], cancelled=exception["cancelled"]
            )
        # Dated events are explicit additions and can take place during vacations.
        holiday = next((h for h in active_holidays if item["type"] in h["types"]), None)
        if holiday and not item.get("event_date"):
            item.update(cancelled=True, cancellation_reason=holiday["name"])
        result.append(item)
    return sorted(result, key=lambda item: (item["start_time"], item["id"]))


def conflict_warnings(entries: list[dict]) -> list[dict]:
    active = [entry for entry in entries if not entry.get("cancelled")]
    return [
        {
            "message": f"Пересекаются «{a['label']}» и «{b['label']}»",
            "entry_ids": [a["id"], b["id"]],
        }
        for i, a in enumerate(active)
        for b in active[i + 1 :]
        if overlaps(a, b)
    ]


class PlannerService:
    """All mutation methods are called inside one request transaction.

    The profile row lock serializes shared-editor changes, validation and imports.
    Database views take the same lock for existing Telegram write paths.
    """

    def __init__(self, conn, settings):
        self.conn = conn
        self.settings = settings

    async def ensure_user(self, user_id: int) -> dict:
        row = await self.conn.fetchrow(
            "INSERT INTO users(id,timezone) VALUES($1,$2) ON CONFLICT(id) DO NOTHING RETURNING *",
            user_id,
            self.settings.default_tz,
        )
        # AFTER INSERT updates default_profile_id, so always re-read the row.
        row = await self.conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        return dict(row)

    async def access(
        self, user_id: int, profile_id: int, write: bool = False, owner: bool = False
    ) -> dict:
        if write or owner:
            await self.conn.fetchval("SELECT id FROM profiles WHERE id=$1 FOR UPDATE", profile_id)
        row = await self.conn.fetchrow(
            "SELECT p.*,m.role FROM profiles p JOIN profile_members m ON m.profile_id=p.id "
            "WHERE p.id=$1 AND m.user_id=$2",
            profile_id,
            user_id,
        )
        if not row:
            raise HTTPException(404, "Профиль не найден или доступ закрыт")
        if (write and row["role"] == "viewer") or (owner and row["role"] != "owner"):
            raise HTTPException(403, "Недостаточно прав для изменения профиля")
        return dict(row)

    async def bootstrap(self, user_id: int) -> dict:
        user = await self.ensure_user(user_id)
        profiles = [
            dict(row)
            for row in await self.conn.fetch(
                "SELECT p.id,p.name,p.color,p.owner_id,p.is_default,m.role FROM profiles p "
                "JOIN profile_members m ON m.profile_id=p.id WHERE m.user_id=$1 "
                "ORDER BY p.is_default DESC,p.created_at,p.id",
                user_id,
            )
        ]
        valid_ids = {p["id"] for p in profiles}
        default = user["default_profile_id"]
        if default not in valid_ids:
            default = (
                profiles[0]["id"]
                if profiles
                else await self.conn.fetchval(
                    "SELECT planner_ensure_profile($1)",
                    user_id,
                )
            )
            await self.conn.execute(
                "UPDATE users SET default_profile_id=$2 WHERE id=$1", user_id, default
            )
            user["default_profile_id"] = default
        return {"user": user, "profiles": profiles, "default_profile_id": default}

    async def update_user(self, user_id: int, payload) -> dict:
        await self.ensure_user(user_id)
        data = payload.model_dump(exclude_unset=True)
        for key in ("timezone", "reminder_minutes", "reminders_enabled", "default_profile_id"):
            if key in data and data[key] is None:
                raise HTTPException(422, "Значение настройки не может быть пустым")
        if data.get("default_profile_id"):
            await self.access(user_id, data["default_profile_id"])
        if data:
            setters = ",".join(f"{key}=${i + 2}" for i, key in enumerate(data))
            await self.conn.execute(
                f"UPDATE users SET {setters},updated_at=now() WHERE id=$1",
                user_id,
                *data.values(),
            )
        return dict(await self.conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id))

    async def create_profile(self, user_id: int, payload) -> dict:
        await self.ensure_user(user_id)
        await self.conn.fetchval("SELECT id FROM users WHERE id=$1 FOR UPDATE", user_id)
        count = await self.conn.fetchval("SELECT count(*) FROM profiles WHERE owner_id=$1", user_id)
        if count >= 20:
            raise HTTPException(409, "Можно создать не более 20 профилей")
        row = await self.conn.fetchrow(
            "INSERT INTO profiles(owner_id,name,color) VALUES($1,$2,$3) RETURNING *",
            user_id,
            payload.name,
            payload.color,
        )
        await self.conn.execute(
            "INSERT INTO profile_members(profile_id,user_id,role) VALUES($1,$2,'owner')",
            row["id"],
            user_id,
        )
        return {**dict(row), "role": "owner"}

    async def update_profile(self, profile_id: int, payload) -> dict:
        data = payload.model_dump(exclude_unset=True)
        if any(value is None for value in data.values()):
            raise HTTPException(422, "Название и цвет не могут быть пустыми")
        if data:
            setters = ",".join(f"{key}=${i + 2}" for i, key in enumerate(data))
            await self.conn.execute(
                f"UPDATE profiles SET {setters} WHERE id=$1", profile_id, *data.values()
            )
        return dict(await self.conn.fetchrow("SELECT * FROM profiles WHERE id=$1", profile_id))

    async def delete_profile(self, profile: dict) -> None:
        if profile["is_default"]:
            raise HTTPException(
                409, "Основной профиль связан с Telegram-ботом и не может быть удалён"
            )
        await self.conn.execute("DELETE FROM profiles WHERE id=$1", profile["id"])
        await self.conn.execute(
            "UPDATE users u SET default_profile_id=p.id FROM profiles p "
            "WHERE p.owner_id=u.id AND p.is_default AND u.default_profile_id IS NULL",
        )

    async def _calendar(self, profile_id: int) -> tuple[list[dict], list[dict], list[dict]]:
        events = [
            dict(row)
            for row in await self.conn.fetch(
                "SELECT * FROM planner_events WHERE profile_id=$1 AND deleted_at IS NULL ORDER BY start_time,id",
                profile_id,
            )
        ]
        exceptions = [
            dict(row)
            for row in await self.conn.fetch(
                "SELECT x.* FROM event_exceptions x JOIN planner_events e ON e.id=x.event_id "
                "WHERE e.profile_id=$1 AND e.deleted_at IS NULL",
                profile_id,
            )
        ]
        holidays = await self.holidays(profile_id)
        return events, exceptions, holidays

    async def day(self, profile_id: int, target_date: date) -> dict:
        events, exceptions, holidays = await self._calendar(profile_id)
        entries = dated_entries(events, exceptions, holidays, target_date)
        return {
            "date": target_date,
            "weekday": target_date.isoweekday(),
            "entries": entries,
            "holidays": [h for h in holidays if h["start_date"] <= target_date <= h["end_date"]],
            "warnings": conflict_warnings(entries),
        }

    async def week(self, profile_id: int, start: date) -> dict:
        if start > date.max - timedelta(days=6):
            raise HTTPException(422, "Дата вне диапазона календаря")
        events, exceptions, holidays = await self._calendar(profile_id)
        days = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            entries = dated_entries(events, exceptions, holidays, day)
            days.append(
                {
                    "date": day,
                    "weekday": day.isoweekday(),
                    "entries": entries,
                    "holidays": [h for h in holidays if h["start_date"] <= day <= h["end_date"]],
                    "warnings": conflict_warnings(entries),
                }
            )
        return {
            "start": start,
            "days": days,
            "holidays": [
                h
                for h in holidays
                if h["start_date"] <= start + timedelta(days=6) and h["end_date"] >= start
            ],
        }

    async def get_event(self, profile_id: int, event_id: int, deleted: bool = False) -> dict:
        row = await self.conn.fetchrow(
            "SELECT * FROM planner_events WHERE profile_id=$1 AND id=$2"
            + ("" if deleted else " AND deleted_at IS NULL"),
            profile_id,
            event_id,
        )
        if not row:
            raise HTTPException(404, "Занятие не найдено")
        return dict(row)

    async def validate_event(self, profile_id: int, data: dict, exclude_id: int = 0) -> list[dict]:
        events, exceptions, holidays = await self._calendar(profile_id)
        events = [e for e in events if e["id"] != exclude_id]
        warnings = {}
        if data.get("event_date"):
            groups = [dated_entries(events, exceptions, holidays, data["event_date"])]
        else:
            groups = [
                [e for e in events if e["weekday"] == data["weekday"] and not e["event_date"]]
            ]
            dates = {
                e["event_date"]
                for e in events
                if e["event_date"] and e["weekday"] == data["weekday"]
            }
            dates.update(x["date"] for x in exceptions if x["date"].isoweekday() == data["weekday"])
            for target in dates:
                if any(
                    h["start_date"] <= target <= h["end_date"] and data["type"] in h["types"]
                    for h in holidays
                ):
                    continue
                groups.append(dated_entries(events, exceptions, holidays, target))
        limit = (
            self.settings.max_lessons_per_day
            if data["type"] == "lesson"
            else self.settings.max_extras_per_day
        )
        for group in groups:
            active = [e for e in group if not e.get("cancelled")]
            if sum(e["type"] == data["type"] for e in active) >= limit:
                raise HTTPException(409, f"Превышен лимит занятий этого типа в день: {limit}")
            for other in active:
                if overlaps(data, other):
                    if data["type"] == other["type"]:
                        raise HTTPException(
                            409, f"Время пересекается с занятием «{other['label']}»"
                        )
                    warnings[other["id"]] = {
                        key: other[key] for key in ("id", "type", "label", "start_time", "end_time")
                    }
        return list(warnings.values())

    async def validate_calendar(self, profile_id: int):
        events, exceptions, holidays = await self._calendar(profile_id)
        groups = [
            [e for e in events if e["weekday"] == weekday and not e["event_date"]]
            for weekday in range(1, 8)
        ]
        dates = {e["event_date"] for e in events if e["event_date"]} | {
            x["date"] for x in exceptions
        }
        groups.extend(dated_entries(events, exceptions, holidays, target) for target in dates)
        for group in groups:
            active = [e for e in group if not e.get("cancelled")]
            for kind, limit in [
                ("lesson", self.settings.max_lessons_per_day),
                ("extra", self.settings.max_extras_per_day),
            ]:
                selected = [e for e in active if e["type"] == kind]
                if len(selected) > limit:
                    raise HTTPException(409, f"Превышен лимит занятий в день: {limit}")
                for i, event in enumerate(selected):
                    for other in selected[i + 1 :]:
                        if overlaps(event, other):
                            raise HTTPException(
                                409,
                                f"Пересекаются «{event['label']}» и «{other['label']}». Проверьте также замены на даты.",
                            )

    async def create_event(self, profile_id: int, payload: EventPayload) -> dict:
        data = payload.model_dump()
        warnings = await self.validate_event(profile_id, data)
        row = await self.conn.fetchrow(
            "INSERT INTO planner_events(profile_id,weekday,type,label,start_time,end_time,location,subtitle,event_date) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *",
            profile_id,
            *(data[key] for key in EVENT_FIELDS),
        )
        await self.validate_calendar(profile_id)
        return {**dict(row), "warnings": warnings}

    async def update_event(self, profile_id: int, event_id: int, payload: EventPayload) -> dict:
        current = await self.get_event(profile_id, event_id)
        if (current["weekday"], current["event_date"]) != (payload.weekday, payload.event_date):
            has_exceptions = await self.conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM event_exceptions WHERE event_id=$1)", event_id
            )
            if has_exceptions:
                raise HTTPException(
                    409, "Сначала удалите замены и отмены этого занятия перед переносом всей серии"
                )
        data = payload.model_dump()
        warnings = await self.validate_event(profile_id, data, event_id)
        setters = ",".join(f"{key}=${i + 3}" for i, key in enumerate(EVENT_FIELDS))
        row = await self.conn.fetchrow(
            f"UPDATE planner_events SET {setters},updated_at=now() WHERE profile_id=$1 AND id=$2 RETURNING *",
            profile_id,
            event_id,
            *(data[key] for key in EVENT_FIELDS),
        )
        await self.validate_calendar(profile_id)
        return {**dict(row), "warnings": warnings}

    async def delete_event(self, profile_id: int, event_id: int) -> dict:
        current = await self.get_event(profile_id, event_id)
        await self.conn.execute(
            "UPDATE planner_events SET deleted_at=now(),updated_at=now() WHERE id=$1", event_id
        )
        return {"deleted": True, "event": current, "restore_available": True}

    async def restore_event(self, profile_id: int, event_id: int) -> dict:
        current = await self.get_event(profile_id, event_id, deleted=True)
        if not current["deleted_at"]:
            return current
        warnings = await self.validate_event(profile_id, current, event_id)
        row = await self.conn.fetchrow(
            "UPDATE planner_events SET deleted_at=NULL,updated_at=now() WHERE id=$1 RETURNING *",
            event_id,
        )
        await self.validate_calendar(profile_id)
        return {**dict(row), "warnings": warnings}

    async def set_exception(self, profile_id: int, event_id: int, payload) -> dict:
        current = await self.get_event(profile_id, event_id)
        if current["event_date"] is not None or current["weekday"] != payload.date.isoweekday():
            raise HTTPException(422, "Замена должна относиться к дате повторяющегося занятия")
        existing = await self.conn.fetchrow(
            "SELECT * FROM event_exceptions WHERE event_id=$1 AND date=$2", event_id, payload.date
        )
        data = {key: (existing[key] if existing else current[key]) for key in OVERRIDE_FIELDS}
        updates = payload.model_dump(exclude_unset=True)
        data.update({key: value for key, value in updates.items() if key in OVERRIDE_FIELDS})
        try:
            validated = EventPayload(**data, weekday=current["weekday"], event_date=payload.date)
        except ValueError as exc:
            raise HTTPException(422, "Проверьте название, тип и время замены") from exc
        warnings = (
            []
            if payload.cancelled
            else await self.validate_event(profile_id, validated.model_dump(), event_id)
        )
        fields = ",".join(OVERRIDE_FIELDS)
        values = ",".join(f"${i}" for i in range(4, 10))
        setters = ",".join(f"{key}=EXCLUDED.{key}" for key in OVERRIDE_FIELDS)
        await self.conn.execute(
            f"INSERT INTO event_exceptions(event_id,date,cancelled,{fields}) VALUES($1,$2,$3,{values}) "
            f"ON CONFLICT(event_id,date) DO UPDATE SET cancelled=EXCLUDED.cancelled,{setters}",
            event_id,
            payload.date,
            payload.cancelled,
            *(data[key] for key in OVERRIDE_FIELDS),
        )
        result = await self.day(profile_id, payload.date)
        return {**next(e for e in result["entries"] if e["id"] == event_id), "warnings": warnings}

    async def remove_exception(self, profile_id: int, event_id: int, target: date) -> dict:
        current = await self.get_event(profile_id, event_id)
        await self.conn.execute(
            "DELETE FROM event_exceptions WHERE event_id=$1 AND date=$2", event_id, target
        )
        # Removing a cancellation must not reintroduce an illegal same-type overlap.
        if current["weekday"] == target.isoweekday():
            await self.validate_event(profile_id, {**current, "event_date": target}, event_id)
        return {"deleted": True}

    async def copy_day(self, profile_id: int, payload) -> dict:
        rows = await self.conn.fetch(
            "SELECT * FROM planner_events WHERE profile_id=$1 AND weekday=$2 AND type=ANY($3::text[]) "
            "AND event_date IS NULL AND deleted_at IS NULL ORDER BY start_time",
            profile_id,
            payload.source_weekday,
            payload.types,
        )
        if not rows:
            raise HTTPException(409, "В исходном дне нет выбранных занятий")
        snapshot = [{key: row[key] for key in EVENT_FIELDS} for row in rows]
        return await self.import_events(
            profile_id,
            [
                {**entry, "weekday": target}
                for target in payload.target_weekdays
                for entry in snapshot
            ],
            payload.target_weekdays,
            payload.types,
            payload.mode,
            payload.preview,
        )

    async def import_events(
        self,
        profile_id: int,
        entries: list[dict],
        weekdays: list[int],
        types: list[str],
        mode: str,
        preview: bool,
    ) -> dict:
        transaction = self.conn.transaction()
        await transaction.start()
        try:
            removed = 0
            if mode == "replace":
                removed = await self.conn.fetchval(
                    "WITH changed AS (UPDATE planner_events SET deleted_at=now(),updated_at=now() "
                    "WHERE profile_id=$1 AND weekday=ANY($2::smallint[]) AND type=ANY($3::text[]) "
                    "AND event_date IS NULL AND deleted_at IS NULL RETURNING id) SELECT count(*) FROM changed",
                    profile_id,
                    weekdays,
                    types,
                )
            created = []
            warnings = []
            for entry in entries:
                new = await self.create_event(profile_id, EventPayload.model_validate(entry))
                created.append(new)
                warnings.extend(new["warnings"])
            result = {
                "created": len(created),
                "removed": removed,
                "entries": created,
                "warnings": warnings,
                "preview": preview,
            }
            if preview:
                await transaction.rollback()
            else:
                await transaction.commit()
            return result
        except BaseException:
            await transaction.rollback()
            raise

    async def holidays(self, profile_id: int) -> list[dict]:
        return [
            dict(row)
            for row in await self.conn.fetch(
                "SELECT * FROM profile_holidays WHERE profile_id=$1 ORDER BY start_date,id",
                profile_id,
            )
        ]

    async def create_holiday(self, profile_id: int, payload) -> dict:
        return dict(
            await self.conn.fetchrow(
                "INSERT INTO profile_holidays(profile_id,name,start_date,end_date,types) VALUES($1,$2,$3,$4,$5) RETURNING *",
                profile_id,
                payload.name,
                payload.start_date,
                payload.end_date,
                payload.types,
            )
        )

    async def remove_holiday(self, profile_id: int, holiday_id: int) -> dict:
        row = await self.conn.fetchrow(
            "DELETE FROM profile_holidays WHERE profile_id=$1 AND id=$2 RETURNING id",
            profile_id,
            holiday_id,
        )
        if not row:
            raise HTTPException(404, "Каникулы не найдены")
        await self.validate_calendar(profile_id)
        return {"deleted": True}

    async def tasks(self, profile_id: int) -> dict:
        rows = await self.conn.fetch(
            "SELECT * FROM planner_tasks WHERE profile_id=$1 ORDER BY completed,due_date,id DESC",
            profile_id,
        )
        attachments = await self.conn.fetch(
            "SELECT a.id,a.task_id,a.filename,a.mime_type,a.size FROM task_attachments a "
            "JOIN planner_tasks t ON t.id=a.task_id WHERE t.profile_id=$1 ORDER BY a.id",
            profile_id,
        )
        by_task = {}
        for attachment in attachments:
            by_task.setdefault(attachment["task_id"], []).append(dict(attachment))
        return {"tasks": [{**dict(row), "attachments": by_task.get(row["id"], [])} for row in rows]}

    async def get_task(self, profile_id: int, task_id: int) -> dict:
        row = await self.conn.fetchrow(
            "SELECT * FROM planner_tasks WHERE profile_id=$1 AND id=$2", profile_id, task_id
        )
        if not row:
            raise HTTPException(404, "Задание не найдено")
        return dict(row)

    async def create_task(self, user_id: int, profile_id: int, payload) -> dict:
        row = await self.conn.fetchrow(
            "INSERT INTO planner_tasks(profile_id,title,subject,description,due_date,completed,created_by) "
            "VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *",
            profile_id,
            payload.title,
            payload.subject,
            payload.description,
            payload.due_date,
            payload.completed,
            user_id,
        )
        return {**dict(row), "attachments": []}

    async def update_task(self, profile_id: int, task_id: int, payload) -> dict:
        current = await self.get_task(profile_id, task_id)
        updates = payload.model_dump(exclude_unset=True)
        try:
            TaskPayload.model_validate(
                {**{key: current[key] for key in TaskPayload.model_fields}, **updates}
            )
        except ValueError as exc:
            raise HTTPException(422, "Проверьте поля задания") from exc
        if updates:
            setters = ",".join(f"{key}=${i + 3}" for i, key in enumerate(updates))
            await self.conn.execute(
                f"UPDATE planner_tasks SET {setters},updated_at=now() WHERE profile_id=$1 AND id=$2",
                profile_id,
                task_id,
                *updates.values(),
            )
        tasks = await self.tasks(profile_id)
        return next(task for task in tasks["tasks"] if task["id"] == task_id)

    async def remove_task(self, profile_id: int, task_id: int) -> dict:
        await self.get_task(profile_id, task_id)
        await self.conn.execute(
            "DELETE FROM planner_tasks WHERE profile_id=$1 AND id=$2", profile_id, task_id
        )
        return {"deleted": True}

    async def members(self, profile_id: int) -> dict:
        members = [
            dict(row)
            for row in await self.conn.fetch(
                "SELECT m.user_id,m.role FROM profile_members m WHERE m.profile_id=$1 ORDER BY m.role,m.user_id",
                profile_id,
            )
        ]
        invites = [
            dict(row)
            for row in await self.conn.fetch(
                "SELECT id,role,expires_at FROM profile_invites WHERE profile_id=$1 AND used_at IS NULL AND expires_at>now() ORDER BY id",
                profile_id,
            )
        ]
        return {"members": members, "invites": invites}

    def token_url(self, key: str, token: str) -> str:
        if self.settings.bot_username:
            prefix = "invite" if key == "invite" else "planner"
            return f"https://t.me/{quote(self.settings.bot_username, safe='')}?start={prefix}_{quote(token)}"
        base = self.settings.webapp_url.rstrip("/")
        return f"{base}/?{key}={quote(token)}" if base else f"?{key}={quote(token)}"

    async def create_invite(self, profile_id: int, role: str) -> dict:
        token = secrets.token_urlsafe(24)
        row = await self.conn.fetchrow(
            "INSERT INTO profile_invites(profile_id,token_hash,role) VALUES($1,$2,$3) RETURNING id,role,expires_at",
            profile_id,
            digest_token(token),
            role,
        )
        return {**dict(row), "token": token, "url": self.token_url("invite", token)}

    async def join_invite(self, user_id: int, token: str) -> dict:
        if len(token) > 128:
            raise HTTPException(404, "Приглашение не найдено")
        await self.ensure_user(user_id)
        invite = await self.conn.fetchrow(
            "SELECT * FROM profile_invites WHERE token_hash=$1 AND expires_at>now() AND used_at IS NULL",
            digest_token(token),
        )
        if not invite:
            raise HTTPException(404, "Приглашение истекло, использовано или отозвано")
        # Same lock order as profile deletion/revocation: profile then invite.
        await self.conn.fetchval(
            "SELECT id FROM profiles WHERE id=$1 FOR UPDATE", invite["profile_id"]
        )
        invite = await self.conn.fetchrow(
            "SELECT * FROM profile_invites WHERE id=$1 AND expires_at>now() AND used_at IS NULL FOR UPDATE",
            invite["id"],
        )
        if not invite:
            raise HTTPException(404, "Приглашение истекло, использовано или отозвано")
        await self.conn.execute(
            "INSERT INTO profile_members(profile_id,user_id,role) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            invite["profile_id"],
            user_id,
            invite["role"],
        )
        await self.conn.execute(
            "UPDATE profile_invites SET used_at=now() WHERE id=$1", invite["id"]
        )
        return await self.access(user_id, invite["profile_id"])

    async def revoke_invite(self, profile_id: int, invite_id: int) -> dict:
        row = await self.conn.fetchrow(
            "DELETE FROM profile_invites WHERE profile_id=$1 AND id=$2 RETURNING id",
            profile_id,
            invite_id,
        )
        if not row:
            raise HTTPException(404, "Приглашение не найдено")
        return {"deleted": True}

    async def remove_member(self, profile_id: int, member_id: int) -> dict:
        role = await self.conn.fetchval(
            "SELECT role FROM profile_members WHERE profile_id=$1 AND user_id=$2",
            profile_id,
            member_id,
        )
        if not role:
            raise HTTPException(404, "Участник не найден")
        if role == "owner":
            raise HTTPException(409, "Нельзя удалить владельца профиля")
        await self.conn.execute(
            "DELETE FROM profile_members WHERE profile_id=$1 AND user_id=$2", profile_id, member_id
        )
        await self.conn.execute(
            "UPDATE users SET default_profile_id=(SELECT id FROM profiles WHERE owner_id=$1 AND is_default) "
            "WHERE id=$1 AND default_profile_id=$2",
            member_id,
            profile_id,
        )
        return {"deleted": True}

    async def create_share(self, profile: dict, payload) -> dict:
        events = await self.conn.fetch(
            "SELECT weekday,type,label,start_time,end_time,location,subtitle,event_date FROM planner_events "
            "WHERE profile_id=$1 AND weekday=ANY($2::smallint[]) AND type=ANY($3::text[]) "
            "AND deleted_at IS NULL AND event_date IS NULL ORDER BY weekday,start_time",
            profile["id"],
            payload.weekdays,
            payload.types,
        )
        snapshot = {
            "profile_name": profile["name"],
            "types": payload.types,
            "weekdays": payload.weekdays,
            "entries": [dict(row) for row in events],
        }
        token = secrets.token_urlsafe(24)
        row = await self.conn.fetchrow(
            "INSERT INTO planner_shares(profile_id,token_hash,snapshot) VALUES($1,$2,$3::jsonb) RETURNING id,expires_at",
            profile["id"],
            digest_token(token),
            json.dumps(jsonable_encoder(snapshot)),
        )
        return {
            **dict(row),
            "token": token,
            "url": self.token_url("share", token),
            "count": len(events),
        }

    async def share(self, token: str) -> dict:
        if len(token) > 128:
            raise HTTPException(404, "Расписание не найдено")
        row = await self.conn.fetchrow(
            "SELECT snapshot,expires_at FROM planner_shares WHERE token_hash=$1 AND expires_at>now()",
            digest_token(token),
        )
        if not row:
            raise HTTPException(404, "Ссылка истекла или была отозвана")
        snapshot = (
            json.loads(row["snapshot"]) if isinstance(row["snapshot"], str) else row["snapshot"]
        )
        return {**snapshot, "expires_at": row["expires_at"]}

    async def import_share(self, token: str, payload) -> dict:
        snapshot = await self.share(token)
        return await self.import_events(
            payload.profile_id,
            snapshot["entries"],
            snapshot["weekdays"],
            snapshot["types"],
            payload.mode,
            payload.preview,
        )

    async def shares(self, profile_id: int) -> dict:
        return {
            "shares": [
                dict(row)
                for row in await self.conn.fetch(
                    "SELECT id,created_at,expires_at FROM planner_shares WHERE profile_id=$1 AND expires_at>now() ORDER BY created_at DESC",
                    profile_id,
                )
            ]
        }

    async def revoke_share(self, profile_id: int, share_id: int) -> dict:
        row = await self.conn.fetchrow(
            "DELETE FROM planner_shares WHERE profile_id=$1 AND id=$2 RETURNING id",
            profile_id,
            share_id,
        )
        if not row:
            raise HTTPException(404, "Ссылка не найдена")
        return {"deleted": True}

    async def bells(self, profile_id: int) -> dict:
        return {
            "slots": [
                dict(row)
                for row in await self.conn.fetch(
                    "SELECT start_time,end_time FROM profile_bells WHERE profile_id=$1 ORDER BY position",
                    profile_id,
                )
            ]
        }

    async def update_bells(self, profile_id: int, payload) -> dict:
        await self.conn.execute("DELETE FROM profile_bells WHERE profile_id=$1", profile_id)
        for position, slot in enumerate(payload.slots, 1):
            await self.conn.execute(
                "INSERT INTO profile_bells(profile_id,position,start_time,end_time) VALUES($1,$2,$3,$4)",
                profile_id,
                position,
                slot.start_time,
                slot.end_time,
            )
        return await self.bells(profile_id)
