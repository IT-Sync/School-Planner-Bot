# Automated PostgreSQL backups

`scripts/backup-postgres.sh` creates a custom-format dump, validates its archive listing, records row counts and non-secret metadata, writes a SHA-256 checksum, and optionally copies the complete set to another host with `rsync`. A lock prevents overlapping runs. Local retention defaults to 14 days.

Production status as of 2026-09-13: the timer is enabled, a local backup and PostgreSQL 16 restore rehearsal passed, and the next scheduled run is active. Off-host replication and external alerting still require operator-provided destinations.

## Production installation

Create a dedicated SSH key and restricted destination on a different host, then install the configuration without committing it:

```bash
sudo install -m 600 deploy/systemd/school-planner-backup.conf.example /etc/school-planner-backup.conf
sudoedit /etc/school-planner-backup.conf
```

Set `BACKUP_REMOTE`, set `BACKUP_REQUIRE_REMOTE=1`, and optionally set `BACKUP_HEALTHCHECK_URL`. The remote directory must already exist. The destination should restrict the key to this backup location and have its own retention or immutable snapshot policy.

Install and activate the timer:

```bash
sudo install -m 644 deploy/systemd/school-planner-backup.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/school-planner-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now school-planner-backup.timer
sudo systemctl start school-planner-backup.service
sudo systemctl status school-planner-backup.service school-planner-backup.timer
```

Inspect recent runs with `journalctl -u school-planner-backup.service`. A successful run ends with `Backup verified:`. Systemd failure is local monitoring; configure the optional healthcheck URL for external missing-run/failure alerts.

## Restore verification

The rehearsal script restores the latest backup into an isolated PostgreSQL 16 container backed by tmpfs, compares important table counts, verifies migrations, and removes the temporary container:

```bash
sudo scripts/rehearse-postgres16.sh
```

Run this regularly and after schema changes. It does not connect applications to the rehearsal database and does not modify production.

## Security and recovery constraints

- Backup files contain users, schedules, homework, and attachment bytes. Keep mode 0600, restrict SSH access, and encrypt the destination storage.
- Do not place credentials in the repository or unit files. Use `/etc/school-planner-backup.conf` and a protected SSH configuration/key.
- A local copy protects against database corruption but not host loss. `BACKUP_REQUIRE_REMOTE=1` makes the job fail when the off-host destination is unavailable or missing.
- Test a full operational restore before declaring the backup system complete.
