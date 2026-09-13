import asyncio
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import httpx
import pytest

os.environ.setdefault("APP_ENV", "test")
from app.webapp.auth import WebAppAuthError, verify_init_data


def signed(uid, token="123:test", age=0):
    data = {"auth_date": str(int(time.time()) - age), "user": json.dumps({"id": uid})}
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret, "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(data)


def test_auth():
    assert verify_init_data(signed(42), "123:test").id == 42
    for value in [
        signed(42, age=4000),
        signed(42, age=-100),
        signed(-1),
        signed(True),
        signed(42) + "&user=%7B%7D",
        signed(42).replace("42", "43"),
    ]:
        with pytest.raises(WebAppAuthError):
            verify_init_data(value, "123:test")


@pytest.fixture
async def client(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if not parts.path.lstrip("/").endswith("_test"):
        raise RuntimeError("Integration tests require a database ending in _test")
    for name, value in {
        "APP_ENV": "test",
        "BOT_TOKEN": "123:test",
        "DATABASE_HOST": parts.hostname,
        "DATABASE_PORT": str(parts.port or 5432),
        "DATABASE_USER": parts.username,
        "DATABASE_PASSWORD": parts.password,
        "DATABASE_NAME": parts.path[1:],
    }.items():
        monkeypatch.setenv(name, value)
    from app.config import get_settings

    get_settings.cache_clear()
    from app.webapp import main

    # Fresh settings/pool for every independent asyncio test loop.
    main.settings = get_settings()
    main.database._settings = main.settings
    async with main.app.router.lifespan_context(main.app):
        await main.database.pool.execute("TRUNCATE users CASCADE")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://test",
            headers={"X-Telegram-Init-Data": signed(101)},
        ) as c:
            yield c


async def request(c, method, url, code=200, **kwargs):
    r = await c.request(method, url, **kwargs)
    assert r.status_code == code, (method, url, r.status_code, r.text)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else r


async def setup_profile(c):
    b = await request(c, "GET", "/api/bootstrap")
    return f"/api/profiles/{b['default_profile_id']}"


@pytest.mark.integration
async def test_postgres_fsm_storage_survives_restart_and_expires(client):
    from dataclasses import replace

    from aiogram.fsm.storage.base import StorageKey

    from app.telegram.fsm_storage import PostgresStorage
    from app.webapp import main

    pool = main.database.pool
    await pool.execute("TRUNCATE bot_fsm_storage")
    key = StorageKey(
        bot_id=10,
        chat_id=-20,
        user_id=30,
        thread_id=40,
        business_connection_id="business",
        destiny="edit",
    )
    storage = PostgresStorage(pool, ttl_seconds=600)
    await storage.set_state(key, "LessonsState:waiting_for_text")
    await storage.set_data(key, {"weekday": 2, "raw_text": "Алгебра"})

    restarted = PostgresStorage(pool, ttl_seconds=600)
    assert await restarted.get_state(key) == "LessonsState:waiting_for_text"
    assert await restarted.get_data(key) == {"weekday": 2, "raw_text": "Алгебра"}
    assert await restarted.update_data(key, {"weekday": 3}) == {
        "weekday": 3,
        "raw_text": "Алгебра",
    }

    variants = [
        replace(key, bot_id=11),
        replace(key, chat_id=-21),
        replace(key, user_id=31),
        replace(key, thread_id=None),
        replace(key, business_connection_id=None),
        replace(key, destiny="other"),
    ]
    for index, variant in enumerate(variants):
        await restarted.set_state(variant, f"variant-{index}")
    assert await restarted.get_state(key) == "LessonsState:waiting_for_text"
    clear_key = variants[0]
    await restarted.set_data(clear_key, {"pending": True})
    await restarted.set_state(clear_key, None)
    assert await restarted.get_data(clear_key) == {"pending": True}
    await restarted.set_data(clear_key, {})
    assert await restarted.get_state(clear_key) is None
    assert await restarted.get_data(clear_key) == {}

    await pool.execute(
        """
        UPDATE bot_fsm_storage SET expires_at = now() - interval '1 second'
        WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3
          AND thread_id IS NOT DISTINCT FROM $4
          AND business_connection_id IS NOT DISTINCT FROM $5 AND destiny = $6
        """,
        *PostgresStorage._key_args(key),
    )
    assert await restarted.get_state(key) is None
    assert await restarted.get_data(key) == {}
    assert await restarted.update_data(key, {"fresh": True}) == {"fresh": True}
    assert await restarted.get_state(key) is None
    await pool.execute(
        """
        UPDATE bot_fsm_storage SET expires_at = now() - interval '1 second'
        WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3
          AND thread_id IS NOT DISTINCT FROM $4
          AND business_connection_id IS NOT DISTINCT FROM $5 AND destiny = $6
        """,
        *PostgresStorage._key_args(key),
    )
    await restarted.cleanup_expired()
    assert await pool.fetchval("SELECT count(*) FROM bot_fsm_storage") == 5

    default_key = StorageKey(bot_id=10, chat_id=20, user_id=30)
    await asyncio.gather(
        *(restarted.update_data(default_key, {f"field_{i}": i}) for i in range(10))
    )
    assert await restarted.get_data(default_key) == {f"field_{i}": i for i in range(10)}
    await restarted.set_state(default_key, "editing")
    await restarted.set_state(default_key, None)
    await restarted.set_data(default_key, {})
    assert await pool.fetchval("SELECT count(*) FROM bot_fsm_storage") == 5


def event(**kwargs):
    return {
        "weekday": 1,
        "type": "lesson",
        "label": "Математика",
        "start_time": "08:30",
        "end_time": "09:15",
        **kwargs,
    }


@pytest.mark.integration
async def test_events_exceptions_copy_and_export(client):
    c = client
    p = await setup_profile(c)
    e = await request(c, "POST", p + "/events", 201, json=event())
    await request(c, "POST", p + "/events", 409, json=event(label="Конфликт"))
    await request(c, "POST", p + "/events", 422, json=event(end_time="08:00"))
    extra = await request(c, "POST", p + "/events", 201, json=event(type="extra", label="Шахматы"))
    assert extra["warnings"]
    await request(
        c,
        "POST",
        p + f"/events/{e['id']}/exceptions",
        json={"date": "2026-09-14", "cancelled": True},
    )
    day = await request(c, "GET", p + "/schedule?date=2026-09-14")
    assert next(x for x in day["entries"] if x["id"] == e["id"])["cancelled"]
    day = await request(c, "GET", p + "/schedule?date=2026-09-21")
    assert not next(x for x in day["entries"] if x["id"] == e["id"])["cancelled"]
    copied = await request(
        c,
        "POST",
        p + "/copy-day",
        json={"source_weekday": 1, "target_weekdays": [2], "preview": True},
    )
    assert copied["created"] == 2
    assert not (await request(c, "GET", p + "/schedule?date=2026-09-15"))["entries"]
    await request(c, "POST", p + "/copy-day", json={"source_weekday": 1, "target_weekdays": [2]})
    assert len((await request(c, "GET", p + "/schedule?date=2026-09-15"))["entries"]) == 2
    await request(c, "DELETE", p + f"/events/{extra['id']}")
    await request(c, "POST", p + f"/events/{extra['id']}/restore")
    ics = await request(c, "GET", p + "/calendar.ics?start=2026-09-14")
    assert "BEGIN:VCALENDAR" in ics.text and "DTSTART:20260914T053000Z" in ics.text
    assert len(ics.text.split("BEGIN:VEVENT")) == 16  # 16 occurrences minus cancelled lesson


@pytest.mark.integration
async def test_roles_sharing_tasks_and_files(client):
    c = client
    p = await setup_profile(c)
    await request(c, "POST", p + "/events", 201, json=event())
    share = await request(c, "POST", p + "/shares", 201, json={})
    invite = await request(c, "POST", p + "/invites", 201, json={"role": "viewer"})
    task = await request(
        c, "POST", p + "/tasks", 201, json={"title": "Прочитать главу", "due_date": "2026-09-14"}
    )
    file = await request(
        c,
        "POST",
        p + f"/tasks/{task['id']}/attachments",
        201,
        files={"file": ("text.txt", "Задание".encode(), "text/plain")},
    )
    await request(
        c,
        "POST",
        p + f"/tasks/{task['id']}/attachments",
        415,
        files={"file": ("bad.html", b"<script>alert(1)</script>", "image/png")},
    )
    c.headers["X-Telegram-Init-Data"] = signed(202)
    own = await setup_profile(c)
    await request(c, "GET", p + "/week?start=2026-09-14", 404)
    await request(c, "GET", p + f"/attachments/{file['id']}", 404)
    await request(c, "POST", f"/api/invites/{invite['token']}/join")
    await request(c, "POST", f"/api/invites/{invite['token']}/join", 404)
    await request(c, "GET", p + "/week?start=2026-09-14")
    await request(c, "POST", p + "/events", 403, json=event())
    await request(c, "PATCH", p + f"/tasks/{task['id']}", 403, json={"completed": True})
    assert (await request(c, "GET", p + f"/attachments/{file['id']}")).text == "Задание"
    result = await request(
        c,
        "POST",
        f"/api/shares/{share['token']}/import",
        json={"profile_id": int(own.split("/")[-1]), "preview": True},
    )
    assert result["created"] == 1
    assert not (await request(c, "GET", own + "/schedule?date=2026-09-14"))["entries"]
    await request(
        c,
        "POST",
        f"/api/shares/{share['token']}/import",
        json={"profile_id": int(own.split("/")[-1])},
    )
    c.headers["X-Telegram-Init-Data"] = signed(101)
    await request(c, "DELETE", p + "/members/202")
    await request(c, "PATCH", p + f"/tasks/{task['id']}", json={"completed": True})
    await request(c, "DELETE", p + f"/shares/{share['id']}")
    await request(c, "GET", f"/api/shares/{share['token']}", 404)
    c.headers["X-Telegram-Init-Data"] = signed(202)
    await request(c, "GET", p + f"/attachments/{file['id']}", 404)


@pytest.mark.integration
async def test_concurrent_conflict_and_legacy_bot(client):
    c = client
    p = await setup_profile(c)
    responses = await asyncio.gather(*(c.post(p + "/events", json=event()) for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    from app.webapp.main import get_schedule_service

    service = get_schedule_service()
    user = await service.user_repo.get_or_create(303)
    assert user.timezone == "Europe/Moscow"
    assert (await service.user_repo.get(303)).id == 303
    await request(c, "POST", "/api/schedule/day", 201, json=event(weekday=3))
    assert len((await request(c, "GET", p + "/schedule?date=2026-09-16"))["entries"]) == 1


@pytest.mark.integration
async def test_holidays_reminders_and_bot_dates(client):
    from datetime import date, datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.reminders import tick
    from app.webapp.main import database, get_schedule_service, settings

    c = client
    p = await setup_profile(c)
    await request(c, "POST", p + "/events", 201, json=event())
    holiday = await request(
        c,
        "POST",
        p + "/holidays",
        201,
        json={"name": "Каникулы", "start_date": "2026-09-14", "end_date": "2026-09-14"},
    )
    await request(
        c, "POST", p + "/events", 201, json=event(event_date="2026-09-14", label="Разовое")
    )
    await request(c, "DELETE", p + f"/holidays/{holiday['id']}", 409)
    view = await get_schedule_service().get_day_view(101, date(2026, 9, 14))
    assert [e.label for e in view.items] == ["Разовое"]
    await request(c, "PATCH", "/api/me", json={"reminders_enabled": True, "reminder_minutes": 15})
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
    now = datetime(2026, 9, 14, 5, 15, 30, tzinfo=timezone.utc)
    await asyncio.gather(
        tick(database.pool, bot, settings, now), tick(database.pool, bot, settings, now)
    )
    assert bot.send_message.await_count == 1
    assert "Разовое" in bot.send_message.call_args.args[1]
    await tick(database.pool, bot, settings, now)
    assert bot.send_message.await_count == 1


@pytest.mark.integration
async def test_migration_preserves_legacy_data(client):
    from pathlib import Path

    from app.webapp.main import database

    async with database.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("CREATE SCHEMA migration_test")
            await conn.execute("SET LOCAL search_path TO migration_test")
            await conn.execute(Path("migrations/0001_init.sql").read_text())
            await conn.execute("INSERT INTO users(id) VALUES(77)")
            await conn.execute(
                "INSERT INTO schedule(user_id,weekday,subject,start_time,end_time) VALUES(77,1,'История','09:00','09:45')"
            )
            await conn.execute(
                "INSERT INTO extras(user_id,weekday,name,start_time,end_time) VALUES(77,2,'Музыка','16:00','17:00')"
            )
            await conn.execute(Path("migrations/0002_planner.sql").read_text())
            assert await conn.fetchval("SELECT count(*) FROM planner_events") == 2
            assert await conn.fetchval("SELECT subject FROM schedule") == "История"
            assert await conn.fetchval("SELECT name FROM extras") == "Музыка"
            assert await conn.fetchval("SELECT timezone FROM users") == "Europe/Amsterdam"
            await conn.execute("UPDATE schedule SET subject='Обществознание' WHERE user_id=77")
            assert (
                await conn.fetchval("SELECT label FROM planner_events WHERE type='lesson'")
                == "Обществознание"
            )
            assert await conn.fetchval("SELECT subject FROM legacy_schedule") == "История"
            await conn.execute("DROP SCHEMA migration_test CASCADE")


@pytest.mark.integration
async def test_request_boundaries(client):
    c = client
    p = await setup_profile(c)
    await request(c, "GET", p + "/week?start=9999-12-31", 422)
    c.headers["X-Telegram-Init-Data"] = "hash=" + urlencode({"v": "я" * 64})[2:]
    await request(c, "GET", "/api/bootstrap", 401)
    c.headers["X-Telegram-Init-Data"] = signed(101)

    async def oversized():
        for _ in range(6):
            yield b"a" * (1024 * 1024)

    await request(c, "POST", p + "/tasks", 413, content=oversized())
    await request(c, "GET", "/api/bootstrap?tgWebAppData=secret", 400)


def test_calendar_unicode_folding():
    from app.planner.calendar import escape, fold

    text = "SUMMARY:" + escape("Название, с; переносом\n" * 10)
    assert all(len(line.encode()) <= 75 for line in fold(text).split("\r\n"))
    assert fold(text).replace("\r\n ", "") == text
