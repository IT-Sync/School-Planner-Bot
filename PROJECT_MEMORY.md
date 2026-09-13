# Project Memory

Last updated: 2026-09-13

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
- Daily local PostgreSQL backups with archive/checksum/count validation and an isolated PostgreSQL 16 restore rehearsal.

Release v2.1.0 implements content-based frontend asset versions, durable PostgreSQL FSM storage, and an operator deployment script. These changes are deployed to production at application commit `b6b858c` (tag `v2.1.0`); GitHub main includes the release and deployment commits (verified through `c61778e`); the v2.1.0 tag and GitHub Release are not yet published. Planned and unfinished work is authoritative in `TODO.md`.

## Technology stack

- Python 3.11+; Docker image uses Python 3.12 slim.
- aiogram 3.31, FastAPI 0.141, asyncpg 0.31, Pydantic 2.13, Uvicorn 0.52.
- PostgreSQL 16 in both the repository's default Compose topology and production.
- Plain HTML/CSS/JavaScript frontend with no Node build step.
- pytest, Playwright Chromium, and Ruff; GitHub Actions CI.

## Main components

- **Bot runtime** — `app/main.py`, `app/telegram/`, `app/services/`, `app/repositories/`. Runs aiogram long polling, legacy command workflows, an HTTP health listener, and the reminder loop. Uses PostgreSQL and Telegram Bot API. FSM conversations persist in `bot_fsm_storage`; writes renew a configurable seven-day TTL, with expiry cleanup at startup and on storage access (at most every five minutes). Per-key event isolation applies within the single bot process.
- **Mini App/API** — `app/webapp/main.py`, `app/planner/`. FastAPI serves static frontend files and both the profile API and a small legacy schedule API. Authenticates Telegram launch data and talks directly to PostgreSQL through asyncpg.
- **Frontend** — `app/webapp/static/index.html`, `planner-v2.css`, `planner-v2.js`. Server-rendered shell plus a DOM-based single-page UI. `styles.css` and `app.js` are compatibility entry points for cached old HTML.
- **Database/migrations** — `app/core/database.py`, `app/migrate.py`, `migrations/`. A shared PostgreSQL database is the source of truth. Migrations are ordered SQL files with stored SHA-256 checksums and an advisory lock.
- **Reminder worker** — `app/reminders.py`. Runs inside the bot process, polls periodically, resolves profile calendars, and sends Telegram messages with durable delivery claims.
- **Deployment/backup** — `Dockerfile`, `docker-compose.yml`, `deploy/systemd/`, `scripts/backup-postgres.sh`, `scripts/rehearse-postgres16.sh`, and operator runbooks under `docs/`.

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
- Static CSS/JS versions are derived from SHA-256 content hashes at process startup, with matching versions rendered into the root HTML and legacy shims. Only URLs carrying the current content hash are immutable. The root document is `no-store`; unversioned legacy assets are `must-revalidate` to recover old Telegram WebView caches.
- Unsaved-form confirmation is implemented inside the Mini App instead of relying on blocking browser `confirm()` behavior.

## Work in progress

Local attachment-navigation fix: images open above the existing task form instead of navigating the WebView to a blob URL. Requests are aborted when the form closes or changes; the Telegram back action closes the image first. Chromium workflows passed at widths 1440 and 390, covering all three preview exit paths, preserved unsaved text/confirmation, object URL cleanup and TXT download; Ruff and diff checks passed. Production remains at the previously verified v2.1.0 build until this fix is deployed.

Release v2.1.0 production rollout is complete; GitHub main includes the release and deployment commits (verified through `c61778e`); the v2.1.0 tag and GitHub Release are not yet published. Automated local backups and restore verification are deployed. Off-host replication/alerting still needs a destination. See `TODO.md`.

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
- Restart the web process after changing frontend files so content hashes and templates reload together. Production now generates hashes automatically: CSS `794b88c6aec37c2f`, JS `01a0ec74d69a309e` for v2.1.0.

## External integrations

- **Telegram Bot API** — aiogram long polling, commands, menu button, reminders, invitations, and schedule deep links. Failure stops bot interaction and notifications; the web process can remain healthy.
- **Telegram Mini Apps** — browser launch data authenticates API requests with Telegram's HMAC scheme and a configurable maximum age.
- **PostgreSQL** — sole durable store for users, calendars, tasks, file bytes, sharing, and reminder delivery records. Both application processes depend on it.
- **HTTPS reverse proxy** — routes the public Mini App domain to the webapp port. Configuration is managed outside the repository.

## Configuration

- `app/config.py` is authoritative; Pydantic Settings reads process environment and `.env`, case-insensitively. Compose injects `.env` and explicitly supplies database/runtime settings.
- Required production settings: `BOT_TOKEN`, `DATABASE_PASSWORD`; practical deployment also needs `BOT_USERNAME` and `WEBAPP_URL`.
- Important controls: `APP_ENV`, database connection variables, `DEFAULT_TZ`, `WEEK_MODE_DEFAULT`, daily event limits, `HEALTH_PORT`, `ADMIN_IDS`, `WEBAPP_AUTH_MAX_AGE`, `REMINDER_POLL_SECONDS`, `FSM_TTL_SECONDS`, `MAX_ATTACHMENT_BYTES`, `WEBAPP_BIND_HOST`, and `WEBAPP_PORT`.
- Never commit `.env`, backups, `pgdata`, or `compose.keep-db.json`; all are ignored.

## Deployment

- A single image supplies `migrate`, `bot`, and `webapp`. Default Compose starts PostgreSQL, waits for it, runs migrations once, then starts bot and webapp as an unprivileged user with dropped capabilities.
- CI validates lint/format, migrations, integration/browser tests, and Docker build. It does not deploy.
- Current production was last verified on 2026-09-13 at application commit `b6b858c` (`v2.1.0`, package/API version `2.1.0`). The public URL is `https://gitflic.it-sync.ru/`, and the checkout is `/opt/pybot/School-Planner-Bot`.
- Production SSH: `alexk@weapp01.it-sync.hl`; run checkout and Docker operations through sudo. Do not store authentication material in project memory.
- Current production uses PostgreSQL 16.15 in the original `school-planner-bot` Compose project. Its ignored `compose.keep-db.json` preserves the established host port and points at external volume `school-planner-bot-postgres16-data-20260913T065348Z`. Every production Compose command must include `-p school-planner-bot -f docker-compose.yml -f compose.keep-db.json`.
- The 2026-09-13 logical cutover preserved PostgreSQL 15 rollback container `school-planner-db-pg15-rollback-20260913T065348Z` and untouched bind directory `/opt/pybot/School-Planner-Bot/pgdata`. Cutover artifacts and instructions are mode-600 files under `backups/cutover-20260913T065348Z`; do not delete them until the retention decision is explicit.
- `school-planner-backup.timer` is enabled and runs daily around 02:15 Europe/Moscow with randomized delay. Backups are currently local under `backups/automatic`; pre-cutover and post-cutover dumps passed checksum, count, migration, and PostgreSQL 16 restore checks on 2026-09-13. Off-host `BACKUP_REMOTE` and external `BACKUP_HEALTHCHECK_URL` are not yet configured.
- v2.1.0 deployment completed with `scripts/deploy-production.sh --allow-local-backup` after a verified manual off-host backup; transfer to the local ignored backup directory was explicitly authorized. Final pre-migration dump: `backups/automatic/planner-20260913T145509Z.dump`; matching copy under `/projects/School-Planner-Bot/backups/releases/v2.1.0/` on the development host. SHA-256 and PostgreSQL 16 restore rehearsal passed. The database container remained `6173c1ea2681`; migration `0003` is applied. Prior application image is retained as `school-planner:rollback`. Persistent off-host scheduling is still unconfigured.
- Follow `docs/safe-update.md` for upgrades and `docs/rescue-old-containers.md` if a second empty Compose stack appears. Never attach PostgreSQL 15 data files directly to PostgreSQL 16.

## Known issues

- When `BOT_USERNAME` is empty, `PlannerService.token_url()` builds invite/share URLs by string concatenation. A `WEBAPP_URL` that already contains a query string can produce a malformed fallback URL. Production currently has `BOT_USERNAME`, so the active path uses Telegram deep links. Tracked in `TODO.md`.

## Known limitations

- FSM state survives bot restarts after migration `0003_fsm_storage.sql`; expired dialogs are discarded (seven days after the last state/data write by default). Existing in-memory production dialogs cannot be migrated.
- ICS is a downloadable 28-day snapshot, not a subscribed calendar feed.
- PNG/JPEG/WebP attachment preview is implemented locally in a separate in-app dialog; it preserves the task form and draft, closes via its back button, Escape or Telegram BackButton, and revokes the object URL on close. Other files keep their download flow. This fix is not yet deployed. Files have no OCR, malware scan, or external object storage.
- Missed reminders are not replayed after downtime, and uncertain Telegram sends are not retried.
- No electronic-diary integration, offline mode, queue service, or horizontal worker coordination exists.
- Off-host backup storage/alerting, proxy configuration, and certificate management are not yet configured in this repository.

## Recent important changes

- Released to production in v2.1.0: automatic asset hashes, PostgreSQL FSM storage with TTL and atomic data updates, and `scripts/deploy-production.sh` with preflight, backup/restore rehearsal, health checks, and attempted application rollback. Production health/readiness, installed version, and public asset hashes were verified after deployment.
- Validation: full PostgreSQL 16 integration and Chromium desktop/mobile suite passed (16 tests), then all seven focused asset/FSM/deployment checks passed after adding partial-stop recovery and concurrent FSM regressions. Ruff, shell syntax, diff whitespace checks, and Docker build (`school-planner:validation`) passed.
- Modern responsive Mini App skin and updated desktop/mobile screenshots.
- Versioned CSS/JS plus legacy asset shims to recover Telegram WebView caches.
- Replaced blocking unsaved-change confirmation with an in-app asynchronous dialog.
- Fixed invisible text on destructive buttons and released frontend assets as `20260913.1`.
- Added daily verified backup tooling/systemd units and passed a PostgreSQL 15 dump restore rehearsal on PostgreSQL 16.
- Migrated production from PostgreSQL 15.13 to 16.15 by logical dump/restore into a separate external volume; retained the stopped PostgreSQL 15 environment for rollback.
- Hardened the restore rehearsal wait so it cannot mistake PostgreSQL's temporary bootstrap server for the final ready server.
- Added family profiles, roles, dated events, tasks/files, holidays, sharing, bells, ICS, and reminders.
- Added transactional migrations, PostgreSQL 15 rescue/update runbooks, CI, browser testing, and hardened Docker runtime defaults.

## Current priorities

1. Configure the prepared backup job with an off-host rsync destination and external missing-run alert.
2. Publish the prepared v2.1.0 tag and GitHub Release when write credentials are available; fix query-safe fallback invite/share URL generation.
3. Decide whether deployment, proxy, and certificate configuration should become infrastructure as code.

## Next recommended steps

- Work through `TODO.md` in priority order.
- Before database or Compose changes, take and validate a custom-format dump and reread the safe-update runbook.
- Add focused tests with each behavior change; run integration tests only against a `_test` database.

## Things that must not be changed casually

- Applied migration files, the `planner_events` canonical model, or writable compatibility views/triggers.
- Profile lock order and transaction boundaries used by API, imports, invitations, and legacy commands.
- Telegram authentication header contract, token hashing, role semantics, or attachment download authorization.
- Reminder claim-before-send semantics without an explicit duplicate/delivery tradeoff decision.
- Production Compose project name, ignored database override, PostgreSQL 16 external volume, or retained PostgreSQL 15 rollback artifacts.
- Public asset names/version query and compatibility shims while older Telegram clients may cache HTML.

## Latest TODO audit

On 2026-09-13, confirmed asset fingerprinting, durable FSM, operator deployment, v2.1.0 rollout, and local backups/restore verification as completed in `TODO.md`. Rechecked production API version 2.1.0 and active backup timer; scheduled remote backup and healthcheck remain unset. Code still contains the fallback URL bug and SQLAlchemy dependency; attachment retention, reminder failure/DST tests, service consolidation and infrastructure documentation/alerts remain open. GitHub main is at `c61778e`; remote v2.1.0 tag is absent and the release lookup returns HTTP 404.

## Memory maintenance notes

Update this snapshot in place, remove obsolete statements, retain only useful recent history, and change `Last updated` whenever project state materially changes. Keep `ARCHITECTURE.md` and `TODO.md` synchronized.
