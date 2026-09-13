#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/pybot/School-Planner-Bot}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups/automatic}"
POSTGRES16_IMAGE="${POSTGRES16_IMAGE:-postgres:16-alpine}"
dump="${1:-}"

if [[ -z "$dump" ]]; then
  dump="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'planner-*.dump' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
fi
[[ -n "$dump" && -s "$dump" ]] || { echo "A non-empty backup dump is required" >&2; exit 1; }

base="${dump%.dump}"
expected="$base.counts"
checksum="$base.sha256"
[[ -s "$expected" && -s "$checksum" ]] || { echo "Backup counts/checksum sidecars are missing" >&2; exit 1; }
(cd "$(dirname "$dump")" && sha256sum --check "$(basename "$checksum")")

container="planner-pg16-rehearsal-$$"
actual="$(mktemp)"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -f "$actual"
}
trap cleanup EXIT

docker run -d --rm --name "$container" \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,noexec,size=512m \
  -e POSTGRES_USER=planner -e POSTGRES_PASSWORD=rehearsal-only -e POSTGRES_DB=planner \
  "$POSTGRES16_IMAGE" >/dev/null

for _ in {1..30}; do
  if docker exec "$container" pg_isready -U planner -d planner >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U planner -d planner >/dev/null
docker exec -i "$container" pg_restore -U planner -d planner --no-owner --exit-on-error <"$dump"

docker exec -i "$container" psql -U planner -d planner -At -F '|' >"$actual" <<'SQL'
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

diff -u "$expected" "$actual"
docker exec "$container" psql -U planner -d planner -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM planner_migrations; SELECT planner_ensure_profile(id) FROM users LIMIT 1;"
printf 'PostgreSQL 16 restore rehearsal passed for %s\n' "$dump"

