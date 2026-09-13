#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

PROJECT_DIR="${PROJECT_DIR:-/opt/pybot/School-Planner-Bot}"
PROJECT_NAME="${PROJECT_NAME:-school-planner-bot}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups/automatic}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
BACKUP_REMOTE="${BACKUP_REMOTE:-}"
BACKUP_REQUIRE_REMOTE="${BACKUP_REQUIRE_REMOTE:-0}"
BACKUP_HEALTHCHECK_URL="${BACKUP_HEALTHCHECK_URL:-}"

notify_failure() {
  local status=$?
  trap - ERR
  if [[ -n "$BACKUP_HEALTHCHECK_URL" ]]; then
    curl --fail --silent --show-error --max-time 10 "${BACKUP_HEALTHCHECK_URL%/}/fail" >/dev/null || true
  fi
  exit "$status"
}
trap notify_failure ERR

cd "$PROJECT_DIR"
mkdir -p "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || { echo "Another backup is already running" >&2; exit 1; }

compose=(docker compose -p "$PROJECT_NAME" -f docker-compose.yml)
if [[ -f compose.keep-db.json ]]; then
  compose+=(-f compose.keep-db.json)
fi

db_id="$("${compose[@]}" ps -q db)"
[[ -n "$db_id" ]] || { echo "Database container is not running" >&2; exit 1; }

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
base="$BACKUP_DIR/planner-$stamp"
dump="$base.dump"
list="$base.list"
counts="$base.counts"
metadata="$base.meta"
checksum="$base.sha256"

docker exec "$db_id" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$dump.partial"
[[ -s "$dump.partial" ]]
docker exec -i "$db_id" sh -c 'pg_restore --list' <"$dump.partial" >"$list.partial"

docker exec -i "$db_id" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|"' >"$counts.partial" <<'SQL'
SELECT 'event_exceptions',count(*) FROM event_exceptions
UNION ALL SELECT 'planner_events',count(*) FROM planner_events
UNION ALL SELECT 'planner_shares',count(*) FROM planner_shares
UNION ALL SELECT 'planner_tasks',count(*) FROM planner_tasks
UNION ALL SELECT 'profile_bells',count(*) FROM profile_bells
UNION ALL SELECT 'profile_holidays',count(*) FROM profile_holidays
UNION ALL SELECT 'profile_invites',count(*) FROM profile_invites
UNION ALL SELECT 'profile_members',count(*) FROM profile_members
UNION ALL SELECT 'profiles',count(*) FROM profiles
UNION ALL SELECT 'reminder_deliveries',count(*) FROM reminder_deliveries
UNION ALL SELECT 'task_attachments',count(*) FROM task_attachments
UNION ALL SELECT 'users',count(*) FROM users
ORDER BY 1;
SQL

{
  printf 'created_utc=%s\n' "$stamp"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD 2>/dev/null || printf unknown)"
  printf 'database_container=%s\n' "$db_id"
  printf 'database_image=%s\n' "$(docker inspect --format '{{.Config.Image}}' "$db_id")"
  printf 'database_version=%s\n' "$(docker exec "$db_id" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "show server_version"')"
} >"$metadata.partial"

mv "$dump.partial" "$dump"
mv "$list.partial" "$list"
mv "$counts.partial" "$counts"
mv "$metadata.partial" "$metadata"
(cd "$BACKUP_DIR" && sha256sum "$(basename "$dump")") >"$checksum.partial"
mv "$checksum.partial" "$checksum"

files=("$dump" "$list" "$counts" "$metadata" "$checksum")
if [[ -n "$BACKUP_REMOTE" ]]; then
  rsync --archive --chmod=F600 "${files[@]}" "${BACKUP_REMOTE%/}/"
elif [[ "$BACKUP_REQUIRE_REMOTE" == "1" ]]; then
  echo "BACKUP_REMOTE is required but not configured" >&2
  exit 1
fi

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'planner-*' -mtime "+$RETENTION_DAYS" -delete

if [[ -n "$BACKUP_HEALTHCHECK_URL" ]]; then
  curl --fail --silent --show-error --max-time 10 "$BACKUP_HEALTHCHECK_URL" >/dev/null
fi

trap - ERR
printf 'Backup verified: %s\n' "$dump"

