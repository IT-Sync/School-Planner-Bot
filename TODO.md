# TODO

Last updated: 2026-09-13

## In progress

Off-host backup replication and missing-run alerting remain active operational work.

## High priority

- [ ] Configure the installed backup timer with an off-host rsync destination and external missing-run alert.
  - Relevant docs: `docs/automated-backups.md`; configuration: `/etc/school-planner-backup.conf` on production.
  - Completed 2026-09-13: daily systemd timer, verified local custom-format dump, checksum/count sidecars, and successful PostgreSQL 16 restore drill.
  - Remaining input: a restricted `user@host:/path` destination and optionally a healthcheck URL. Set `BACKUP_REQUIRE_REMOTE=1` after configuring it.

## Medium priority

- [ ] Publish prepared v2.1.0 commit/tag and GitHub Release once write credentials are available.
  - Application commit: `b6b858c`; annotated local and production tag: `v2.1.0`.
  - Release notes: `docs/releases/v2.1.0.md`.
  - Production rollout is complete: asset hashes, durable FSM migration, application health/readiness, and package/API version verified.
  - Deployment used a verified manual off-host copy with explicit user authorization; configure permanent off-host backups separately.

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
