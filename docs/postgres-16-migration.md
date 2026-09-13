# Production PostgreSQL 15 to 16 migration

Production currently keeps PostgreSQL 15 and its original `pgdata` bind mount through `compose.keep-db.json`. The target topology uses PostgreSQL 16 and a new volume. Migration is logical (`pg_dump`/`pg_restore`); never mount version-15 data files into PostgreSQL 16.

## Preconditions

- A recent automated backup exists locally and off-host, its checksum passes, and `scripts/rehearse-postgres16.sh` succeeds.
- A maintenance window and rollback owner are agreed.
- Free disk space is sufficient for both database stores and dumps.
- Current container IDs, image versions, row counts, `.env`, Compose configuration, and Git commit are recorded.
- Bot and webapp can be stopped for the final consistent dump.

## Rehearsal

Run the backup and isolated restore without stopping production:

```bash
sudo scripts/backup-postgres.sh
sudo scripts/rehearse-postgres16.sh
```

The rehearsal must validate the archive checksum, restore without errors, match important table counts, and execute the migration/profile functions on PostgreSQL 16. Retain the journal output with the change record.

## Cutover plan

1. Stop `bot` and `webapp`; leave PostgreSQL 15 running.
2. Create and verify a final dump with the backup script, then copy it off-host.
3. Preserve `compose.keep-db.json`, the old container inspection, and `pgdata`; do not delete or rename them.
4. Create a separate PostgreSQL 16 container/volume with the same database name and credentials, without publishing it to the application network name yet.
5. Restore the final dump with `--no-owner --exit-on-error`, run migrations, compare table counts, and perform integrity queries.
6. Switch the Compose `db` service to the new PostgreSQL 16 volume, start `webapp`, verify `/ready` and authenticated read/write flows, then start `bot`.
7. Verify reminders, bot commands, Mini App profiles/tasks/files, public assets, logs, and a fresh post-cutover backup.
8. Keep the stopped PostgreSQL 15 container and `pgdata` unchanged until the rollback window closes.

Exact cutover commands must be generated from the then-current resolved Compose configuration; do not hardcode credentials or volume names in this document.

## Rollback

If validation fails, stop new writers, restore the original `compose.keep-db.json`, start the unchanged PostgreSQL 15 container, and restart the previous application release. Data written only after PostgreSQL 16 cutover requires a reverse logical migration and is not covered by container rollback, so decide the acceptable rollback window before cutover.
