"""Apply versioned migrations once: python -m app.migrate."""

import asyncio

from app.config import get_settings
from app.core.database import Database


async def main():
    database = Database(get_settings().model_copy(update={"auto_migrate": False}))
    await database.connect()
    try:
        await database._run_migrations()
        print("Database migrations applied successfully")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
