# TODO

Last updated: 2026-09-12

## In progress

No active repository work is currently recorded.

## High priority

- [ ] Configure automated, monitored, off-host production PostgreSQL backups and perform a restore drill.
  - Relevant docs: `docs/safe-update.md`, `docs/rescue-old-containers.md`.
  - Reason: backups are currently an operator-run procedure; attachments and all planner state exist only in PostgreSQL.

- [ ] Plan and rehearse the production PostgreSQL 15 to 16 logical migration before cutover.
  - Relevant files: `docker-compose.yml`, `migrations/`, `scripts/keep-existing-db.py`.
  - Reason: production intentionally uses PostgreSQL 15 with `pgdata`, while clean deployments use PostgreSQL 16 with a named volume. Never reuse the version-15 data directory directly.

## Medium priority

- [ ] Automate frontend asset fingerprinting or centralize the release version.
  - Relevant files: `app/webapp/static/index.html`, `styles.css`, `app.js`.
  - Reason: the current cache-recovery strategy requires manually updating versioned CSS/JS references and compatibility shims together.

- [ ] Decide whether bot FSM state must survive restarts; use durable storage if required.
  - Relevant code: `MemoryStorage` in `app/main.py`, state definitions in `app/telegram/states.py`.
  - Reason: current editing conversations are discarded whenever the bot container restarts.

- [ ] Define and automate the production deployment workflow after backup policy is in place.
  - Relevant files: `.github/workflows/check.yml`, `docs/safe-update.md`.
  - Reason: CI validates commits, but server deployment, health verification, and rollback remain manual.

## Low priority

- [ ] Review and remove the unused SQLAlchemy runtime dependency if no planned code requires it.
  - Relevant files: `pyproject.toml`, `requirements.lock`.
  - Reason: current persistence code uses asyncpg directly.

- [ ] Add retention and size monitoring for database-backed task attachments.
  - Relevant code: attachment endpoints in `app/planner/api.py`; table `task_attachments` in `migrations/0002_planner.sql`.
  - Reason: file bytes have no expiry and increase database and backup size.

## Known bugs

- [ ] Conditional malformed fallback invite/share links when `BOT_USERNAME` is unset and `WEBAPP_URL` contains a query string.
  - Relevant code: `PlannerService.token_url()` in `app/planner/service.py`.
  - Current string concatenation can produce a malformed URL such as a query followed by `/?invite=...`; add tests for URLs with and without existing query parameters.
  - The verified production configuration uses `BOT_USERNAME`, so this is not the active link path.

## Technical debt

- [ ] Reduce duplication between profile-oriented `PlannerService` and compatibility `ScheduleService` only after defining regression coverage for old bot commands and legacy API endpoints.
  - Relevant code: `app/planner/service.py`, `app/services/schedule_service.py`, `app/repositories/`, writable compatibility views in `migrations/0002_planner.sql`.
  - Preserve profile locks, transactional validation, and existing command behavior.

- [ ] Add focused tests for reminder failure status and timezone/DST boundary behavior.
  - Relevant code: `app/reminders.py`, existing coverage in `tests/test_planner.py`.
  - Current tests cover duplicate suppression and dated calendar behavior but not every delivery-failure or time-transition path.

## Infrastructure / deployment

- [ ] Document or codify the production reverse proxy, TLS renewal, firewall rules, and monitoring after confirming their owner and implementation.
  - The proxy and certificate configuration are outside this repository and were not confidently identifiable during memory initialization.

- [ ] Add disk and database growth alerts, especially for PostgreSQL and Docker image usage.
  - Production has limited root filesystem headroom and attachments are stored inside PostgreSQL.

## Documentation

No separate documentation task is open. Continuous memory maintenance is required by `AGENTS.md` and is part of each substantial task.

## Future improvements

- [ ] Evaluate a subscribed calendar feed only if stable token revocation and privacy requirements are defined; current ICS export is a 28-day snapshot.
- [ ] Evaluate electronic-diary import, OCR, or object storage only after selecting external providers and defining data/privacy constraints.
