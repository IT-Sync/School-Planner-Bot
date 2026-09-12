# Project Memory

Last updated: 2026-09-12

## Project purpose

School Planner is a Russian-language Telegram bot and Telegram Mini App for pupils and families. It manages recurring and dated lessons, extracurricular activities, homework, shared family profiles, calendar exports, and Telegram reminders.

## Current state

The main user workflows are implemented and deployed. The current Mini App has a responsive modern UI, day/week views, settings, tasks, sharing, and accessible in-app confirmation dialogs. Telegram commands remain supported through a compatibility layer.

Implemented:

- Telegram bot commands and FSM editing, including `/today`, `/week`, `/web`, `/share`, legacy lesson/extras editing, and admin statistics commands.
- Profile-based Mini App with owner/editor/viewer roles, recurring and dated events, exceptions, holidays, copy/import previews, tasks, attachments, bells, and ICS export.
- One-time family invitations and seven-day schedule snapshots; legacy bot share links remain separate and expire after one day.
- Opt-in event reminders and evening summaries from the bot process.
- Transactional, checksummed SQL migrations and migration of legacy schedules into the profile model.
- Integration and real-browser tests in GitHub Actions.

No feature is currently marked in progress. Planned and unfinished work is authoritative in `TODO.md`.

## Technology stack

- Python 3.11+; Docker image uses Python 3.12 slim.
- aiogram 3.31, FastAPI 0.141, asyncpg 0.31, Pydantic 2.13, Uvicorn 0.52.
- PostgreSQL 16 in the repository's default Compose topology; current production intentionally remains on PostgreSQL 15.
- Plain HTML/CSS/JavaScript frontend with no Node build step.
- pytest, Playwright Chromium, and Ruff; GitHub Actions CI.

## Main components

- **Bot runtime** — `app/main.py`, `app/telegram/`, `app/services/`, `app/repositories/`. Runs aiogram long polling, legacy command workflows, an HTTP health listener, and the reminder loop. Uses PostgreSQL and Telegram Bot API.
- **Mini App/API** — `app/webapp/main.py`, `app/planner/`. FastAPI serves static frontend files and both the profile API and a small legacy schedule API. Authenticates Telegram launch data and talks directly to PostgreSQL through asyncpg.
- **Frontend** — `app/webapp/static/index.html`, `planner-v2.css`, `planner-v2.js`. Server-rendered shell plus a DOM-based single-page UI. `styles.css` and `app.js` are compatibility entry points for cached old HTML.
- **Database/migrations** — `app/core/database.py`, `app/migrate.py`, `migrations/`. A shared PostgreSQL database is the source of truth. Migrations are ordered SQL files with stored SHA-256 checksums and an advisory lock.
- **Reminder worker** — `app/reminders.py`. Runs inside the bot process, polls periodically, resolves profile calendars, and sends Telegram messages with durable delivery claims.
- **Deployment** — `Dockerfile`, `docker-compose.yml`, `docs/safe-update.md`, `docs/rescue-old-containers.md`, `scripts/keep-existing-db.py`.

## Repository map

```text
app/planner/       Current profile API, calendar rules, validation and import logic
app/webapp/        FastAPI application, Telegram auth, request limits and static UI
app/telegram/      Telegram handlers, keyboards and FSM state definitions
app/services/      Compatibility services for established bot workflows
app/repositories/  asyncpg repositories used by compatibility services
migrations/        Versioned transactional PostgreSQL schema changes
tests/             Integration and Playwright browser coverage
docs/              Operator runbooks, development notes and UI screenshots
.github/workflows/ CI checks, tests and Docker build
```

## Implemented functionality

- Calendar resolution combines weekly templates, one-off dated events, per-date cancellations/replacements, and holiday ranges.
- Same-type overlaps are rejected; lesson/extra overlaps are warnings. Per-day limits are configurable.
- Mutations lock the profile row so concurrent editors cannot bypass conflict checks. Preview imports execute using the normal logic inside a rolled-back transaction.
- Tasks support up to five validated PDF/PNG/JPEG/WebP/UTF-8 TXT files, normally limited to 5 MiB each, stored in PostgreSQL `BYTEA`.
- Profile invitations are single-use. Share tokens and invite tokens are stored only as SHA-256 digests.
- Static assets use versioned immutable URLs. The root document is `no-store`; unversioned legacy assets are `must-revalidate` to recover old Telegram WebView caches.
- Unsaved-form confirmation is implemented inside the Mini App instead of relying on blocking browser `confirm()` behavior.

## Work in progress

There is no active implementation branch or unfinished feature recorded. See `TODO.md` for prioritized work.

## Important technical decisions

- `planner_events` is the canonical event store. Writable `schedule` and `extras` SQL views preserve established Telegram commands; their triggers write into `planner_events`. Do not create a second schedule store.
- `PlannerService` handles the profile model and current API. `ScheduleService` plus repositories remains for bot/legacy compatibility. Consolidation must preserve public behavior and concurrency locking.
- A new user gets a default profile through database trigger/function `planner_ensure_profile`.
- API mutations run in one request transaction. Owner/write access locks the profile row before authorization-sensitive changes and validation.
- Reminder claims are committed before calling Telegram. Failed or uncertain sends are not retried automatically, which favors avoiding duplicates over guaranteed delivery.
- Attachments live in PostgreSQL, not the filesystem. Backup/restore must include the database.
- Migrations are append-only. Editing an applied migration causes migration failure because its checksum changes.

## Operational constraints

- Production requires a Telegram bot token, public HTTPS Mini App URL, PostgreSQL, and a reverse proxy. Proxy implementation and certificate automation are outside this repository.
- The repository exposes the webapp on loopback `${WEBAPP_PORT:-11002}` by default. PostgreSQL is internal to Compose in a new installation.
- Production Mini App access requires valid Telegram `initData` in `X-Telegram-Init-Data`; query-string credentials are rejected. Development fallback identity is forbidden when `APP_ENV=production`.
- Integration tests truncate `users CASCADE` and must only use a disposable database whose name ends in `_test`.
- Frontend asset releases must change versioned URLs in `index.html` and both legacy compatibility shims until automated fingerprinting exists.

## External integrations

- **Telegram Bot API** — aiogram long polling, commands, menu button, reminders, invitations, and schedule deep links. Failure stops bot interaction and notifications; the web process can remain healthy.
- **Telegram Mini Apps** — browser launch data authenticates API requests with Telegram's HMAC scheme and a configurable maximum age.
- **PostgreSQL** — sole durable store for users, calendars, tasks, file bytes, sharing, and reminder delivery records. Both application processes depend on it.
- **HTTPS reverse proxy** — routes the public Mini App domain to the webapp port. Configuration is managed outside the repository.

## Configuration

- `app/config.py` is authoritative; Pydantic Settings reads process environment and `.env`, case-insensitively. Compose injects `.env` and explicitly supplies database/runtime settings.
- Required production settings: `BOT_TOKEN`, `DATABASE_PASSWORD`; practical deployment also needs `BOT_USERNAME` and `WEBAPP_URL`.
- Important controls: `APP_ENV`, database connection variables, `DEFAULT_TZ`, `WEEK_MODE_DEFAULT`, daily event limits, `HEALTH_PORT`, `ADMIN_IDS`, `WEBAPP_AUTH_MAX_AGE`, `REMINDER_POLL_SECONDS`, `MAX_ATTACHMENT_BYTES`, `WEBAPP_BIND_HOST`, and `WEBAPP_PORT`.
- Never commit `.env`, backups, `pgdata`, or `compose.keep-db.json`; all are ignored.

## Deployment

- A single image supplies `migrate`, `bot`, and `webapp`. Default Compose starts PostgreSQL, waits for it, runs migrations once, then starts bot and webapp as an unprivileged user with dropped capabilities.
- CI validates lint/format, migrations, integration/browser tests, and Docker build. It does not deploy.
- Current production was last verified on 2026-09-12. Application containers were rebuilt from `ba28333`; later `0da5c0b` changed only screenshots. The public URL is `https://gitflic.it-sync.ru/?v=20260912.1`, and the checkout is `/opt/pybot/School-Planner-Bot`.
- Current production intentionally preserves the original `school-planner-bot` Compose project and PostgreSQL 15 container with its `pgdata` bind mount through an ignored `compose.keep-db.json`. Every production Compose command must include `-p school-planner-bot -f docker-compose.yml -f compose.keep-db.json`.
- Follow `docs/safe-update.md` for upgrades and `docs/rescue-old-containers.md` if a second empty Compose stack appears. Never attach PostgreSQL 15 data files directly to PostgreSQL 16.

## Known issues

- When `BOT_USERNAME` is empty, `PlannerService.token_url()` builds invite/share URLs by string concatenation. A `WEBAPP_URL` that already contains a query string can produce a malformed fallback URL. Production currently has `BOT_USERNAME`, so the active path uses Telegram deep links. Tracked in `TODO.md`.

## Known limitations

- FSM state uses aiogram `MemoryStorage` and is lost on bot restart.
- ICS is a downloadable 28-day snapshot, not a subscribed calendar feed.
- Files have no preview, OCR, malware scan, or external object storage.
- Missed reminders are not replayed after downtime, and uncertain Telegram sends are not retried.
- No electronic-diary integration, offline mode, queue service, or horizontal worker coordination exists.
- Production backup scheduling, proxy configuration, and certificate management are not represented as code here.

## Recent important changes

- Modern responsive Mini App skin and updated desktop/mobile screenshots.
- Versioned CSS/JS plus legacy asset shims to recover Telegram WebView caches.
- Replaced blocking unsaved-change confirmation with an in-app asynchronous dialog.
- Added family profiles, roles, dated events, tasks/files, holidays, sharing, bells, ICS, and reminders.
- Added transactional migrations, PostgreSQL 15 rescue/update runbooks, CI, browser testing, and hardened Docker runtime defaults.

## Current priorities

1. Establish automated, monitored, off-host production backups.
2. Plan and rehearse the production PostgreSQL 15 to 16 migration.
3. Fix query-safe fallback invite/share URL generation and automate frontend asset fingerprinting.
4. Decide whether deployment, proxy, and certificate configuration should become infrastructure as code.

## Next recommended steps

- Work through `TODO.md` in priority order.
- Before database or Compose changes, take and validate a custom-format dump and reread the safe-update runbook.
- Add focused tests with each behavior change; run integration tests only against a `_test` database.

## Things that must not be changed casually

- Applied migration files, the `planner_events` canonical model, or writable compatibility views/triggers.
- Profile lock order and transaction boundaries used by API, imports, invitations, and legacy commands.
- Telegram authentication header contract, token hashing, role semantics, or attachment download authorization.
- Reminder claim-before-send semantics without an explicit duplicate/delivery tradeoff decision.
- Production Compose project name, ignored database override, PostgreSQL version, or `pgdata` mount.
- Public asset names/version query and compatibility shims while older Telegram clients may cache HTML.

## Memory maintenance notes

Update this snapshot in place, remove obsolete statements, retain only useful recent history, and change `Last updated` whenever project state materially changes. Keep `ARCHITECTURE.md` and `TODO.md` synchronized.
