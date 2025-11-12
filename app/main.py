from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import get_settings
from app.core.database import Database
from app.core.logging import configure_logging
from app.health import start_health_server
from app.repositories import ExtrasRepository, ScheduleRepository, UserRepository
from app.services import ScheduleService
from app.telegram import handlers


async def main() -> None:
    configure_logging()
    settings = get_settings()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    database = Database(settings)
    await database.connect()
    health_server = await start_health_server(port=settings.health_port)

    schedule_repo = ScheduleRepository(database.pool)
    extras_repo = ExtrasRepository(database.pool)
    user_repo = UserRepository(database.pool)
    schedule_service = ScheduleService(settings, user_repo, schedule_repo, extras_repo)

    handlers.configure_dependencies(schedule_service, settings)

    dp.include_router(handlers.router)

    try:
        await dp.start_polling(bot)
    finally:
        health_server.close()
        await health_server.wait_closed()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
