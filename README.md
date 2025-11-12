## School Planner Bot

Телеграм-бот, который помогает школьникам и родителям вести расписание уроков и внеурочных активностей. MVP реализует сценарии из `plan.md`: заполнение уроков и внеурочки по дням, просмотр `/today` и `/week`, валидации пересечений внутри типа и лимиты записей.

### Архитектура
- **Python 3.11 + aiogram 3** — бот и слой презентации Telegram.
- **PostgreSQL 15** — хранение пользователей, уроков и внеурочки (см. `migrations/0001_init.sql`).
- **Сервисы домена** (`app/services/*`) инкапсулируют правки данных и отдачу DTO/представлений для Telegram.
- **Репозитории** (`app/repositories/*`) работают поверх `asyncpg` и чистого SQL, чтобы гарантировать контроль над индексами и проверками.
- **Валидаторы и парсеры** (`app/utils/parsing.py`) преобразуют пользовательский текст в DTO, проверяют форматы времени и пересечения.
- Всё приложение и база запускаются в контейнерах через `docker compose`; используем нестандартные порты (см. `docker-compose.yml`).

### Переменные окружения
Скопируйте `.env.example` в `.env` и заполните:

```
BOT_TOKEN=<telegram bot token>
DATABASE_HOST=db
DATABASE_PORT=5544
DATABASE_USER=planner
DATABASE_PASSWORD=planner
DATABASE_NAME=planner
DEFAULT_TZ=Europe/Amsterdam
WEEK_MODE_DEFAULT=combined
MAX_LESSONS_PER_DAY=12
MAX_EXTRAS_PER_DAY=6
HEALTH_PORT=8088
```

### Локальный запуск (после реализации кода)
```
docker compose up --build
```
Команда применит миграции и запустит бота в отдельном контейнере. Postgres станет доступен на `localhost:5544`, бот — на `localhost:8088` (health-check endpoint).

