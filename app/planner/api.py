from datetime import date, timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.planner.schemas import (
    BellsPayload,
    CopyDayPayload,
    EventPayload,
    ExceptionPayload,
    HolidayPayload,
    InvitePayload,
    ProfilePatch,
    ProfilePayload,
    ShareImportPayload,
    SharePayload,
    TaskPatch,
    TaskPayload,
    UserPatch,
)
from app.planner.service import PlannerService


def create_router(database, get_current_user, settings):
    router = APIRouter(prefix="/api")

    async def service():
        async with database.pool.acquire() as conn:
            async with conn.transaction():
                yield PlannerService(conn, settings)

    S = Annotated[PlannerService, Depends(service, scope="function")]
    U = Annotated[object, Depends(get_current_user)]

    # Local annotations are resolved here, not via module globals.
    @router.get("/bootstrap")
    async def bootstrap(s: S, u: U):
        return await s.bootstrap(u.id)

    @router.patch("/me")
    async def me(payload: UserPatch, s: S, u: U):
        return await s.update_user(u.id, payload)

    @router.get("/profiles")
    async def profiles(s: S, u: U):
        return (await s.bootstrap(u.id))["profiles"]

    @router.post("/profiles", status_code=201)
    async def create_profile(payload: ProfilePayload, s: S, u: U):
        return await s.create_profile(u.id, payload)

    @router.patch("/profiles/{pid}")
    async def update_profile(pid: int, payload: ProfilePatch, s: S, u: U):
        await s.access(u.id, pid, owner=True)
        return await s.update_profile(pid, payload)

    @router.delete("/profiles/{pid}")
    async def delete_profile(pid: int, s: S, u: U):
        profile = await s.access(u.id, pid, owner=True)
        await s.delete_profile(profile)
        return {"deleted": True}

    @router.get("/profiles/{pid}/week")
    async def week(pid: int, start: date, s: S, u: U):
        await s.access(u.id, pid)
        return await s.week(pid, start)

    @router.get("/profiles/{pid}/schedule")
    async def day(pid: int, date: date, s: S, u: U):
        await s.access(u.id, pid)
        return await s.day(pid, date)

    @router.get("/profiles/{pid}/calendar.ics")
    async def calendar(pid: int, start: date, s: S, u: U):
        from app.planner.calendar import export_calendar

        if start > date.max - timedelta(days=27):
            raise HTTPException(422, "Дата вне диапазона календаря")

        profile = await s.access(u.id, pid)
        user = await s.ensure_user(u.id)
        days = []
        for offset in range(0, 28, 7):
            days.extend((await s.week(pid, start + timedelta(days=offset)))["days"])
        return Response(
            export_calendar(profile, days, user["timezone"]),
            media_type="text/calendar",
            headers={"Content-Disposition": 'attachment; filename="school-planner.ics"'},
        )

    @router.post("/profiles/{pid}/events", status_code=201)
    async def create_event(pid: int, payload: EventPayload, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.create_event(pid, payload)

    @router.get("/profiles/{pid}/events/{eid}")
    async def get_event(pid: int, eid: int, s: S, u: U):
        await s.access(u.id, pid)
        return await s.get_event(pid, eid)

    @router.put("/profiles/{pid}/events/{eid}")
    async def update_event(pid: int, eid: int, payload: EventPayload, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.update_event(pid, eid, payload)

    @router.delete("/profiles/{pid}/events/{eid}")
    async def delete_event(pid: int, eid: int, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.delete_event(pid, eid)

    @router.post("/profiles/{pid}/events/{eid}/restore")
    async def restore(pid: int, eid: int, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.restore_event(pid, eid)

    @router.post("/profiles/{pid}/events/{eid}/exceptions")
    async def exception(pid: int, eid: int, payload: ExceptionPayload, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.set_exception(pid, eid, payload)

    @router.delete("/profiles/{pid}/events/{eid}/exceptions/{target}")
    async def remove_exception(pid: int, eid: int, target: date, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.remove_exception(pid, eid, target)

    @router.post("/profiles/{pid}/copy-day")
    async def copy_day(pid: int, payload: CopyDayPayload, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.copy_day(pid, payload)

    @router.get("/profiles/{pid}/holidays")
    async def holidays(pid: int, s: S, u: U):
        await s.access(u.id, pid)
        return {"holidays": await s.holidays(pid)}

    @router.post("/profiles/{pid}/holidays", status_code=201)
    async def holiday(pid: int, payload: HolidayPayload, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.create_holiday(pid, payload)

    @router.delete("/profiles/{pid}/holidays/{hid}")
    async def remove_holiday(pid: int, hid: int, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.remove_holiday(pid, hid)

    @router.get("/profiles/{pid}/tasks")
    async def tasks(pid: int, s: S, u: U):
        await s.access(u.id, pid)
        return await s.tasks(pid)

    @router.post("/profiles/{pid}/tasks", status_code=201)
    async def create_task(pid: int, payload: TaskPayload, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.create_task(u.id, pid, payload)

    @router.patch("/profiles/{pid}/tasks/{tid}")
    async def update_task(pid: int, tid: int, payload: TaskPatch, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.update_task(pid, tid, payload)

    @router.delete("/profiles/{pid}/tasks/{tid}")
    async def delete_task(pid: int, tid: int, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.remove_task(pid, tid)

    @router.post("/profiles/{pid}/tasks/{tid}/attachments", status_code=201)
    async def attach(pid: int, tid: int, s: S, u: U, file: UploadFile = File(...)):
        await s.access(u.id, pid, write=True)
        await s.get_task(pid, tid)
        data = await file.read(min(settings.max_attachment_bytes, 5242880) + 1)
        await file.close()
        if not data or len(data) > min(settings.max_attachment_bytes, 5242880):
            raise HTTPException(413, "Размер файла должен быть от 1 байта до 5 МБ")
        # Verify signatures rather than trusting a caller-provided MIME type.
        mime = None
        if data.startswith(b"%PDF-"):
            mime = "application/pdf"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            mime = "image/webp"
        elif (file.filename or "").lower().endswith(".txt"):
            try:
                data.decode("utf-8")
                mime = "text/plain"
            except UnicodeDecodeError:
                pass
        if not mime:
            raise HTTPException(415, "Поддерживаются PDF, PNG, JPEG, WebP и UTF-8 TXT")
        count = await s.conn.fetchval("SELECT count(*) FROM task_attachments WHERE task_id=$1", tid)
        if count >= 5:
            raise HTTPException(409, "Можно прикрепить не более 5 файлов к заданию")
        filename = (file.filename or "attachment").replace("\\", "/").split("/")[-1][:180]
        return dict(
            await s.conn.fetchrow(
                "INSERT INTO task_attachments(task_id,filename,mime_type,size,data) VALUES($1,$2,$3,$4,$5) "
                "RETURNING id,task_id,filename,mime_type,size",
                tid,
                filename,
                mime,
                len(data),
                data,
            )
        )

    @router.get("/profiles/{pid}/attachments/{aid}")
    async def download(pid: int, aid: int, s: S, u: U):
        await s.access(u.id, pid)
        row = await s.conn.fetchrow(
            "SELECT a.* FROM task_attachments a JOIN planner_tasks t ON t.id=a.task_id WHERE t.profile_id=$1 AND a.id=$2",
            pid,
            aid,
        )
        if not row:
            raise HTTPException(404, "Файл не найден")
        return Response(
            bytes(row["data"]),
            media_type=row["mime_type"],
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(row["filename"], safe=""),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @router.delete("/profiles/{pid}/attachments/{aid}")
    async def remove_attachment(pid: int, aid: int, s: S, u: U):
        await s.access(u.id, pid, write=True)
        row = await s.conn.fetchrow(
            "DELETE FROM task_attachments a USING planner_tasks t WHERE a.task_id=t.id AND t.profile_id=$1 AND a.id=$2 RETURNING a.id",
            pid,
            aid,
        )
        if not row:
            raise HTTPException(404, "Файл не найден")
        return {"deleted": True}

    @router.get("/profiles/{pid}/members")
    async def members(pid: int, s: S, u: U):
        await s.access(u.id, pid, owner=True)
        return await s.members(pid)

    @router.post("/profiles/{pid}/invites", status_code=201)
    async def invite(pid: int, payload: InvitePayload, s: S, u: U):
        await s.access(u.id, pid, owner=True)
        return await s.create_invite(pid, payload.role)

    @router.delete("/profiles/{pid}/invites/{iid}")
    async def revoke_invite(pid: int, iid: int, s: S, u: U):
        await s.access(u.id, pid, owner=True)
        return await s.revoke_invite(pid, iid)

    @router.post("/invites/{token}/join")
    async def join(token: str, s: S, u: U):
        return await s.join_invite(u.id, token)

    @router.delete("/profiles/{pid}/members/{uid}")
    async def remove_member(pid: int, uid: int, s: S, u: U):
        await s.access(u.id, pid, owner=True)
        return await s.remove_member(pid, uid)

    @router.post("/profiles/{pid}/shares", status_code=201)
    async def create_share(pid: int, payload: SharePayload, s: S, u: U):
        profile = await s.access(u.id, pid, write=True)
        return await s.create_share(profile, payload)

    @router.get("/profiles/{pid}/shares")
    async def shares(pid: int, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.shares(pid)

    @router.delete("/profiles/{pid}/shares/{sid}")
    async def revoke_share(pid: int, sid: int, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.revoke_share(pid, sid)

    @router.get("/shares/{token}")
    async def share(token: str, s: S, u: U):
        return await s.share(token)

    @router.post("/shares/{token}/import")
    async def import_share(token: str, payload: ShareImportPayload, s: S, u: U):
        await s.access(u.id, payload.profile_id, write=True)
        return await s.import_share(token, payload)

    @router.get("/profiles/{pid}/bells")
    async def bells(pid: int, s: S, u: U):
        await s.access(u.id, pid)
        return await s.bells(pid)

    @router.put("/profiles/{pid}/bells")
    async def update_bells(pid: int, payload: BellsPayload, s: S, u: U):
        await s.access(u.id, pid, write=True)
        return await s.update_bells(pid, payload)

    return router
