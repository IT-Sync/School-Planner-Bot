from __future__ import annotations

from pathlib import Path

import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.core.database import Database
from app.repositories import ExtrasRepository, ScheduleRepository, ShareTokenRepository, UserRepository
from app.services import ScheduleService
from app.services.errors import InputValidationError
from app.domain import DayItemType, EditableEntry
from app.webapp.auth import WebAppAuthError, WebAppUser, verify_init_data
from app.webapp.schemas import (
    CreateEntryRequest,
    DayScheduleResponse,
    EntryType,
    ScheduleEntry,
    UpdateEntryRequest,
    WeekScheduleResponse,
)

settings = get_settings()
logger = logging.getLogger("school_planner.webapp")
database = Database(settings)
_schedule_service: ScheduleService | None = None


async def lifespan(app: FastAPI):
    global _schedule_service
    await database.connect()
    user_repo = UserRepository(database.pool)
    schedule_repo = ScheduleRepository(database.pool)
    extras_repo = ExtrasRepository(database.pool)
    share_repo = ShareTokenRepository(database.pool)
    _schedule_service = ScheduleService(settings, user_repo, schedule_repo, extras_repo, share_repo)
    yield
    await database.close()


app = FastAPI(
    title="School Planner WebApp API",
    version="1.1.0",
    lifespan=lifespan,
)
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


def get_schedule_service() -> ScheduleService:
    if _schedule_service is None:
        raise RuntimeError("ScheduleService is not initialized")
    return _schedule_service


def get_current_user(init_data: str | None = Header(None, alias="X-Telegram-Init-Data")) -> WebAppUser:
    if init_data:
        logger.debug("Received initData length=%s", len(init_data))
        try:
            return verify_init_data(init_data, settings.bot_token)
        except WebAppAuthError as exc:
            logger.warning("WebApp auth failed: %s", exc)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if settings.webapp_dev_user_id:
        logger.info("WebApp dev fallback user_id=%s", settings.webapp_dev_user_id)
        return WebAppUser(id=settings.webapp_dev_user_id, first_name="Dev")
    logger.warning("Missing initData and dev fallback disabled")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing initData")


def _entry_to_schedule_entry(entry: EditableEntry) -> ScheduleEntry:
    return ScheduleEntry(
        id=entry.id,
        type=EntryType(entry.type.value),
        label=entry.label,
        start_time=entry.start_time,
        end_time=entry.end_time,
        location=entry.location,
        subtitle=entry.subtitle,
    )


def _map_entry_type(entry_type: EntryType) -> DayItemType:
    return DayItemType(entry_type.value)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    if not static_dir.exists():
        return HTMLResponse("<h1>WebApp bundle not found</h1>", status_code=500)
    html_path = static_dir / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/schedule/day", response_model=DayScheduleResponse)
async def get_day_schedule(
    weekday: int = Query(..., ge=1, le=7),
    user: WebAppUser = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> DayScheduleResponse:
    entries = await service.get_editable_entries(user.id, weekday)
    return DayScheduleResponse(
        weekday=weekday,
        entries=[_entry_to_schedule_entry(entry) for entry in entries],
    )


@app.get("/api/schedule/week", response_model=WeekScheduleResponse)
async def get_week_schedule(
    user: WebAppUser = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> WeekScheduleResponse:
    week_map: dict[int, list[ScheduleEntry]] = {}
    for weekday in range(1, 8):
        entries = await service.get_editable_entries(user.id, weekday)
        week_map[weekday] = [_entry_to_schedule_entry(entry) for entry in entries]
    return WeekScheduleResponse(week=week_map)


@app.post("/api/schedule/day", response_model=ScheduleEntry, status_code=status.HTTP_201_CREATED)
async def create_entry(
    payload: CreateEntryRequest,
    user: WebAppUser = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> ScheduleEntry:
    try:
        created = await service.create_entry(
            user.id,
            payload.weekday,
            _map_entry_type(payload.type),
            payload.label,
            payload.start_time,
            payload.end_time,
            payload.location,
            payload.subtitle,
        )
    except InputValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.errors) from exc
    return _entry_to_schedule_entry(created)


@app.put("/api/schedule/item/{entry_id}", response_model=ScheduleEntry)
async def update_entry(
    entry_id: int,
    payload: UpdateEntryRequest,
    user: WebAppUser = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> ScheduleEntry:
    try:
        updated = await service.update_entry(
            user.id,
            _map_entry_type(payload.type),
            entry_id,
            label=payload.label,
            start_time_value=payload.start_time,
            end_time_value=payload.end_time,
            location=payload.location,
            subtitle=payload.subtitle,
            weekday=payload.weekday,
        )
    except InputValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.errors) from exc
    return _entry_to_schedule_entry(updated)


@app.delete("/api/schedule/item/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: int,
    entry_type: EntryType = Query(..., alias="type"),
    user: WebAppUser = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> None:
    deleted = await service.delete_entry(user.id, _map_entry_type(entry_type), entry_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запись не найдена")
