# Разработка и проверки

## Локальная среда

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip install -e '.[dev]' -c requirements.lock
```

Используйте отдельную базу для разработки. Настройте переменные из `.env.example`, задайте `APP_ENV=development`, `WEBAPP_DEV_USER_ID=10001`, соединение с PostgreSQL. Токен бота для веб-разработки не нужен.

```bash
python -m app.migrate
uvicorn app.webapp.main:app --host 127.0.0.1 --port 18002 --reload --no-access-log
```

Откройте `http://127.0.0.1:18002`. При разработке с dev-ID все запросы без Telegram-данных выполняются от имени этого пользователя, поэтому сервер слушает только loopback. Запуск реального бота — `python -m app.main` с действующим токеном.

## Тесты

Тесты интеграции очищают `users CASCADE`. Они допускают только явно указанную базу с именем, заканчивающимся на `_test`. Никогда не указывайте рабочую базу.

```bash
docker run -d --name planner-tests \
  -e POSTGRES_USER=planner_test -e POSTGRES_PASSWORD=local-test-only \
  -e POSTGRES_DB=planner_test -p 127.0.0.1:5549:5432 \
  --tmpfs /var/lib/postgresql/data postgres:16-alpine

export APP_ENV=test BOT_TOKEN=123:test
export DATABASE_HOST=127.0.0.1 DATABASE_PORT=5549
export DATABASE_USER=planner_test DATABASE_PASSWORD=local-test-only DATABASE_NAME=planner_test
export TEST_DATABASE_URL=postgresql://planner_test:local-test-only@127.0.0.1:5549/planner_test
python -m app.migrate
ruff check app tests
ruff format --check app tests
pytest -q
```

Браузерные тесты сами поднимают веб-сервер на свободном локальном порту, создают отдельный профиль и завершают процесс после проверки:

```bash
python -m playwright install --with-deps chromium
RUN_BROWSER_TESTS=1 pytest -q
```

Покрыты: подпись и срок Telegram-авторизации; CRUD занятий; конфликты и конкурентная запись; отмены на дату; каникулы; предпросмотр копирования и импорта без изменения данных; роли и отзыв доступа; файлы; экспорт ICS; перенос старой схемы; чтение дат ботом; отсутствие повторной отправки напоминаний. Chromium проверяет создание и замену занятия, задание с вложением, завершение задания, настройки, переключение дня/недели и отсутствие горизонтальной прокрутки на ширинах 390 и 1440.

GitHub Actions выполняет линтер, миграции, тесты и Docker build. Снимки интерфейса сохраняются как артефакты. Тесты используют имитацию отправки Telegram: рабочие сообщения пользователям не отправляются.

## Структура

- `app/planner/` — API, модели входных данных, календарь, права и импорт.
- `app/webapp/` — авторизация, ASGI-приложение, ограничение тела запросов и интерфейс.
- `app/reminders.py` — очередь попыток отправки и периодическая проверка.
- `app/services/`, `app/repositories/`, `app/telegram/` — совместимость команд бота.
- `migrations/` — SQL, упакованный вместе с приложением; новые изменения схемы добавляются отдельными файлами.
- `requirements.lock` — проверенные runtime-зависимости Docker; при обновлении синхронизируйте ограничения `pyproject.toml`, пересоберите образ и выполните проверки.

В текущую поставку не входят интеграции с электронными дневниками, OCR, офлайн-синхронизация и автоматическая подписка внешнего календаря. Такие расширения требуют отдельных договорённостей об источниках данных и API.
