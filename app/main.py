from __future__ import annotations

import asyncio
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from app.config import get_settings
from app.core.database import Database
from app.core.logging import configure_logging
from app.health import start_health_server
from app.reminders import run_reminders
from app.repositories import (
    ExtrasRepository,
    ScheduleRepository,
    ShareTokenRepository,
    StatsRepository,
    UserRepository,
)
from app.services import AdminService, ScheduleService
from app.telegram import handlers


async def main() -> None:
    configure_logging()
    settings = get_settings()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher(storage=MemoryStorage())
    await bot.set_my_commands(
        [
            BotCommand(command="web", description="Открыть школьный планер"),
            BotCommand(command="today", description="Расписание на сегодня"),
            BotCommand(command="week", description="Расписание на неделю"),
        ]
    )

    if settings.webapp_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Планер", web_app=WebAppInfo(url=settings.webapp_url))
        )

    database = Database(settings)
    await database.connect()
    health_server = await start_health_server(port=settings.health_port)

    schedule_repo = ScheduleRepository(database.pool)
    extras_repo = ExtrasRepository(database.pool)
    share_repo = ShareTokenRepository(database.pool)
    stats_repo = StatsRepository(database.pool)
    user_repo = UserRepository(database.pool)
    schedule_service = ScheduleService(settings, user_repo, schedule_repo, extras_repo, share_repo)
    admin_service = AdminService(stats_repo)

    handlers.configure_dependencies(schedule_service, settings, admin_service)

    dp.include_router(handlers.router)

    reminders = asyncio.create_task(run_reminders(database.pool, bot, settings))
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        with suppress(asyncio.CancelledError):
            await reminders
        health_server.close()
        await health_server.wait_closed()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
