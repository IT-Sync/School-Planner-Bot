#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

usage() {
  cat <<'EOF'
Usage: scripts/deploy-production.sh [--dry-run] [--allow-local-backup]

Build and deploy the current clean checkout without recreating PostgreSQL.

  --dry-run             Run read-only preflight checks and print the plan.
  --allow-local-backup  Permit deployment when off-host backup is not enforced.
                        Use only during a documented backup-storage outage.
  -h, --help            Show this help.

Optional environment:
  DEPLOY_EXPECTED_COMMIT       Require HEAD to match this commit exactly.
  DEPLOY_PUBLIC_HEALTH_URL     Verify this public health URL after deployment.
  DEPLOY_HEALTH_TIMEOUT        Container health timeout in seconds (default: 180).
  BACKUP_CONFIG                Backup environment file
                               (default: /etc/school-planner-backup.conf).
EOF
}

dry_run=0
allow_local_backup=0
while (($#)); do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --allow-local-backup) allow_local_backup=1 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
default_project_dir="$(cd -- "$script_dir/.." && pwd)"
backup_config="${BACKUP_CONFIG:-/etc/school-planner-backup.conf}"

if [[ -e "$backup_config" && ! -r "$backup_config" ]]; then
  echo "Backup configuration is not readable: $backup_config (run with suitable privileges)" >&2
  exit 1
fi
if [[ -r "$backup_config" ]]; then
  set -a
  # The file is an operator-managed systemd EnvironmentFile containing shell-style assignments.
  # shellcheck disable=SC1090
  source "$backup_config"
  set +a
fi

PROJECT_DIR="${PROJECT_DIR:-$default_project_dir}"
PROJECT_NAME="${PROJECT_NAME:-school-planner-bot}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups/automatic}"
export PROJECT_DIR PROJECT_NAME BACKUP_DIR
DEPLOY_HEALTH_TIMEOUT="${DEPLOY_HEALTH_TIMEOUT:-180}"
DEPLOY_EXPECTED_COMMIT="${DEPLOY_EXPECTED_COMMIT:-}"
DEPLOY_PUBLIC_HEALTH_URL="${DEPLOY_PUBLIC_HEALTH_URL:-}"

die() {
  echo "Deployment refused: $*" >&2
  exit 1
}

command -v docker >/dev/null || die "docker is required"
command -v git >/dev/null || die "git is required"
command -v flock >/dev/null || die "flock is required"
if [[ -n "$DEPLOY_PUBLIC_HEALTH_URL" || -n "${BACKUP_HEALTHCHECK_URL:-}" ]]; then
  command -v curl >/dev/null || die "curl is required for configured health checks"
fi
[[ "$DEPLOY_HEALTH_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || die "DEPLOY_HEALTH_TIMEOUT must be a positive integer"

cd "$PROJECT_DIR"
[[ -f docker-compose.yml ]] || die "docker-compose.yml is missing in $PROJECT_DIR"
[[ -f compose.keep-db.json ]] || die "compose.keep-db.json is required in production"
[[ -f .env ]] || die ".env is missing"
[[ -x scripts/backup-postgres.sh ]] || die "scripts/backup-postgres.sh is not executable"
[[ -x scripts/rehearse-postgres16.sh ]] || die "scripts/rehearse-postgres16.sh is not executable"

override_mode="$(stat -c '%a' compose.keep-db.json)"
(( (8#$override_mode & 077) == 0 )) || die "compose.keep-db.json must not be accessible by group or others"

exec 9>"${TMPDIR:-/tmp}/school-planner-production-deploy.lock"
flock -n 9 || die "another production deployment is running"

compose=(docker compose -p "$PROJECT_NAME" -f docker-compose.yml -f compose.keep-db.json)
"${compose[@]}" config --quiet
services="$("${compose[@]}" config --services)"
for required_service in db migrate bot webapp; do
  grep -Fxq "$required_service" <<<"$services" || die "Compose service is missing: $required_service"
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$PROJECT_DIR is not a Git checkout"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || die "Git checkout has uncommitted or untracked files"
target_commit="$(git rev-parse HEAD)"
if [[ -n "$DEPLOY_EXPECTED_COMMIT" ]]; then
  expected_commit="$(git rev-parse "${DEPLOY_EXPECTED_COMMIT}^{commit}" 2>/dev/null)" \
    || die "DEPLOY_EXPECTED_COMMIT cannot be resolved"
  [[ "$target_commit" == "$expected_commit" ]] \
    || die "HEAD $target_commit does not match expected commit $expected_commit"
fi

db_id="$("${compose[@]}" ps -q db)"
[[ -n "$db_id" ]] || die "database container is not running"
db_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$db_id")"
[[ "$db_health" == "healthy" ]] || die "database container is not healthy (status: $db_health)"

if [[ "${BACKUP_REQUIRE_REMOTE:-0}" == "1" ]]; then
  [[ -n "${BACKUP_REMOTE:-}" ]] || die "BACKUP_REQUIRE_REMOTE=1 but BACKUP_REMOTE is empty"
elif [[ "$allow_local_backup" != "1" ]]; then
  die "off-host backup enforcement is disabled; configure BACKUP_REQUIRE_REMOTE=1 or pass --allow-local-backup explicitly"
fi

printf 'Preflight passed: project=%s commit=%s database=%s\n' "$PROJECT_NAME" "$target_commit" "$db_id"
if [[ "$dry_run" == "1" ]]; then
  cat <<EOF
Dry-run only; no containers, images, database rows, or backup files were changed.
Planned steps:
  1. Build the migrate, bot, and webapp image from $target_commit.
  2. Stop bot and webapp while leaving database $db_id running.
  3. Create a verified backup and rehearse its restore on isolated PostgreSQL 16.
  4. Run transactional migrations with --no-deps.
  5. Recreate only bot and webapp, then wait for health/readiness.
  6. Confirm that the database container ID is still $db_id.
EOF
  exit 0
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
deploy_record="$BACKUP_DIR/deploy-$stamp"
mkdir -p "$deploy_record"

bot_id="$("${compose[@]}" ps -q bot)"
webapp_id="$("${compose[@]}" ps -q webapp)"
[[ -n "$bot_id" && -n "$webapp_id" ]] || die "bot and webapp must be running before deployment"
previous_bot_image="$(docker inspect --format '{{.Image}}' "$bot_id")"
previous_webapp_image="$(docker inspect --format '{{.Image}}' "$webapp_id")"
[[ "$previous_bot_image" == "$previous_webapp_image" ]] \
  || die "bot and webapp use different images; manual review is required"
rollback_tag="school-planner:rollback"
docker image tag "$previous_bot_image" "$rollback_tag"

cat >"$deploy_record/state" <<EOF
started_utc=$stamp
target_commit=$target_commit
database_container=$db_id
previous_application_image=$previous_bot_image
rollback_tag=$rollback_tag
EOF

apps_stopped=0
apps_recreated=0
deployment_complete=0
on_exit() {
  local status=$?
  if [[ "$status" == "0" || "$deployment_complete" == "1" ]]; then
    return
  fi
  trap - EXIT
  echo "Deployment failed; attempting to restore the previous application image" >&2
  if [[ "$apps_recreated" == "1" ]]; then
    if docker image tag "$rollback_tag" school-planner:local; then
      "${compose[@]}" up -d --no-deps --force-recreate bot webapp \
        || echo "Automatic application rollback failed; manual recovery is required" >&2
    else
      echo "Cannot restore rollback image; manual recovery is required" >&2
    fi
  elif [[ "$apps_stopped" == "1" ]]; then
    docker start "$bot_id" "$webapp_id" \
      || echo "Cannot restart previous containers; manual recovery is required" >&2
  fi
  if [[ -d "$deploy_record" ]]; then
    printf 'failed_utc=%s\n' "$(date -u +%Y%m%dT%H%M%SZ)" >>"$deploy_record/state" || true
  fi
  echo "Database restore was not attempted. Review $deploy_record and container logs." >&2
  exit "$status"
}
trap on_exit EXIT

echo "Building application image for $target_commit"
"${compose[@]}" build migrate bot webapp

echo "Stopping application writers; PostgreSQL remains online"
apps_stopped=1
"${compose[@]}" stop bot webapp
[[ "$("${compose[@]}" ps -q db)" == "$db_id" ]] || die "database container changed after stopping applications"

echo "Creating and verifying the final pre-deployment backup"
backup_output="$(scripts/backup-postgres.sh)"
printf '%s\n' "$backup_output"
backup_dump="$(sed -n 's/^Backup verified: //p' <<<"$backup_output" | tail -n 1)"
[[ -n "$backup_dump" && -s "$backup_dump" ]] || die "backup script did not report a valid dump"
scripts/rehearse-postgres16.sh "$backup_dump"
printf 'backup_dump=%s\n' "$backup_dump" >>"$deploy_record/state"

echo "Applying database migrations"
"${compose[@]}" run --rm --no-deps migrate
[[ "$("${compose[@]}" ps -q db)" == "$db_id" ]] || die "database container changed during migrations"

echo "Recreating application containers"
apps_recreated=1
"${compose[@]}" up -d --no-deps --force-recreate bot webapp

wait_for_health() {
  local service="$1" deadline cid status
  deadline=$((SECONDS + DEPLOY_HEALTH_TIMEOUT))
  while ((SECONDS < deadline)); do
    cid="$("${compose[@]}" ps -q "$service")"
    if [[ -n "$cid" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")"
      if [[ "$status" == "healthy" ]]; then
        return 0
      fi
      if [[ "$status" == "exited" || "$status" == "dead" || "$status" == "unhealthy" ]]; then
        "${compose[@]}" logs --tail=100 "$service" >&2 || true
        return 1
      fi
    fi
    sleep 2
  done
  "${compose[@]}" logs --tail=100 "$service" >&2 || true
  echo "Timed out waiting for $service health" >&2
  return 1
}

wait_for_health webapp
wait_for_health bot
"${compose[@]}" exec -T webapp python -c \
  'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=5).read()'
if [[ -n "$DEPLOY_PUBLIC_HEALTH_URL" ]]; then
  curl --fail --silent --show-error --max-time 15 "$DEPLOY_PUBLIC_HEALTH_URL" >/dev/null
fi
[[ "$("${compose[@]}" ps -q db)" == "$db_id" ]] || die "database container changed during application deployment"

printf 'completed_utc=%s\n' "$(date -u +%Y%m%dT%H%M%SZ)" >>"$deploy_record/state"
deployment_complete=1
trap - EXIT
printf 'Deployment completed: commit=%s backup=%s rollback-image=%s\n' \
  "$target_commit" "$backup_dump" "$rollback_tag"
