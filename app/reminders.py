"""Opt-in reminders with durable claims. Uncertain deliveries are not replayed."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.planner.service import PlannerService

log = logging.getLogger(__name__)


def upcoming(entries, local_now, minutes, grace_seconds=120):
    for entry in entries:
        if entry.get("cancelled"):
            continue
        start = datetime.combine(local_now.date(), entry["start_time"], tzinfo=local_now.tzinfo)
        due = start - timedelta(minutes=minutes)
        if 0 <= (local_now - due).total_seconds() < grace_seconds and local_now <= start:
            yield entry


async def deliver(pool, bot, uid, pid, key, day, kind, text):
    # Commit claim BEFORE Telegram send. Concurrent workers and restarts cannot
    # send the same claim twice, including a timeout after successful delivery.
    claimed = await pool.fetchval(
        """INSERT INTO reminder_deliveries(user_id,profile_id,event_key,delivery_date,kind)
        SELECT $1,$2,$3,$4,$5 WHERE EXISTS (
            SELECT 1 FROM profile_members m JOIN users u ON u.id=m.user_id
            WHERE m.user_id=$1 AND m.profile_id=$2 AND u.reminders_enabled)
        ON CONFLICT DO NOTHING RETURNING user_id""",
        uid,
        pid,
        key,
        day,
        kind,
    )
    if claimed is None:
        return False
    try:
        message = await bot.send_message(uid, text[:3900], parse_mode=None)
    except Exception as exc:
        await pool.execute(
            """UPDATE reminder_deliveries SET status='failed',error=$6
            WHERE user_id=$1 AND profile_id=$2 AND event_key=$3 AND delivery_date=$4 AND kind=$5""",
            uid,
            pid,
            key,
            day,
            kind,
            type(exc).__name__,
        )
        log.warning("Reminder delivery failed: %s", type(exc).__name__)
        return False
    await pool.execute(
        """UPDATE reminder_deliveries SET status='sent',message_id=$6,sent_at=now()
        WHERE user_id=$1 AND profile_id=$2 AND event_key=$3 AND delivery_date=$4 AND kind=$5""",
        uid,
        pid,
        key,
        day,
        kind,
        message.message_id,
    )
    return True


async def tick(pool, bot, settings, now=None):
    now = now or datetime.now(timezone.utc)
    users = await pool.fetch("""SELECT u.id,u.timezone,u.reminder_minutes,u.evening_time,
        p.id AS profile_id,p.name FROM users u JOIN profile_members m ON m.user_id=u.id
        JOIN profiles p ON p.id=m.profile_id WHERE u.reminders_enabled ORDER BY u.id,p.id""")
    for user in users:
        try:
            local = now.astimezone(ZoneInfo(user["timezone"]))
            async with pool.acquire() as conn:
                service = PlannerService(conn, settings)
                today = await service.day(user["profile_id"], local.date())
                next_day = None
                evening = user["evening_time"]
                if (
                    evening
                    and 0
                    <= (
                        local - datetime.combine(local.date(), evening, tzinfo=local.tzinfo)
                    ).total_seconds()
                    < 120
                ):
                    next_day = await service.day(
                        user["profile_id"], local.date() + timedelta(days=1)
                    )
                    tasks = await conn.fetch(
                        """SELECT title FROM planner_tasks WHERE profile_id=$1
                        AND due_date=$2 AND NOT completed ORDER BY id LIMIT 20""",
                        user["profile_id"],
                        next_day["date"],
                    )
            # Also inspect tomorrow for lead times that cross midnight.
            days = [today]
            if user["reminder_minutes"] and local.hour >= 22:
                async with pool.acquire() as conn:
                    tomorrow = await PlannerService(conn, settings).day(
                        user["profile_id"], local.date() + timedelta(days=1)
                    )
                days.append(tomorrow)
            for day in days:
                for entry in day["entries"]:
                    if entry.get("cancelled"):
                        continue
                    start = datetime.combine(day["date"], entry["start_time"], tzinfo=local.tzinfo)
                    if (
                        not 0
                        <= (
                            local - (start - timedelta(minutes=user["reminder_minutes"]))
                        ).total_seconds()
                        < 120
                    ):
                        continue
                    if local > start + timedelta(seconds=60):
                        continue
                    text = f"{user['name']} · Скоро занятие\n{entry['start_time'].strftime('%H:%M')}–{entry['end_time'].strftime('%H:%M')} {entry['label']}"
                    if entry.get("location"):
                        text += "\n" + entry["location"]
                    await deliver(
                        pool,
                        bot,
                        user["id"],
                        user["profile_id"],
                        f"{entry['id']}:{entry['start_time']}",
                        day["date"],
                        "event",
                        text,
                    )
            if next_day is not None:
                lines = [f"{user['name']} · План на завтра, {next_day['date'].strftime('%d.%m')}"]
                lines.extend(
                    f"{e['start_time'].strftime('%H:%M')} {e['label']}"
                    for e in next_day["entries"]
                    if not e.get("cancelled")
                )
                if len(lines) == 1:
                    lines.append("Занятий нет — свободный день.")
                if tasks:
                    lines.extend(["\nДомашние задания:"] + [f"• {t['title']}" for t in tasks])
                await deliver(
                    pool,
                    bot,
                    user["id"],
                    user["profile_id"],
                    "summary",
                    local.date(),
                    "evening",
                    "\n".join(lines),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("Reminder tick failed: %s", type(exc).__name__)


async def run_reminders(pool, bot, settings):
    while True:
        try:
            await tick(pool, bot, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("Reminder loop error: %s", type(exc).__name__)
        await asyncio.sleep(settings.reminder_poll_seconds)
