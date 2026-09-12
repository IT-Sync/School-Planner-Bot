# Восстановление после запуска нового Compose рядом со старым

Эта инструкция применяется, когда заполненная PostgreSQL 15 продолжает работать
в проекте `school-planner-bot`, а новый Compose уже создал отдельный проект
`school-planner` с пустой PostgreSQL 16.

Не удаляйте контейнеры, тома и каталог `pgdata`. Новый проект сначала остановите:

```bash
cd /opt/pybot/School-Planner-Bot
set -euo pipefail
docker ps -q --filter label=com.docker.compose.project=school-planner | xargs -r docker stop

old_db="$(docker ps -q \
  --filter label=com.docker.compose.project=school-planner-bot \
  --filter label=com.docker.compose.service=db)"
old_bot="$(docker ps -q \
  --filter label=com.docker.compose.project=school-planner-bot \
  --filter label=com.docker.compose.service=bot)"
old_web="$(docker ps -q \
  --filter label=com.docker.compose.project=school-planner-bot \
  --filter label=com.docker.compose.service=webapp)"
test -n "$old_db" && test -n "$old_bot" && test -n "$old_web"
# `docker ps -q` returns a short ID, while `docker compose ps -q` returns a full
# ID. Normalize it before the later identity check.
old_db="$(docker inspect --format '{{.Id}}' "$old_db")"
docker inspect --format '{{.Name}} {{.Config.Image}} {{range .Mounts}}{{.Source}} -> {{.Destination}}{{end}}' "$old_db"
```

Последняя команда должна показать старый `postgres:15` и исходный каталог
`/opt/pybot/School-Planner-Bot/pgdata` (либо фактический старый том). Если вывод
другой, остановитесь и выясните, где находится заполненная база.

Создайте согласованную резервную копию после остановки старых процессов записи:

```bash
umask 077
backup="$PWD/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
cp .env "$backup/env.before"
git rev-parse HEAD > "$backup/git-before.txt"
docker inspect "$old_db" > "$backup/db-container.json"
docker stop "$old_bot" "$old_web"
docker exec "$old_db" sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT (SELECT count(*) FROM users)||'\''|'\''||(SELECT count(*) FROM schedule)||'\''|'\''||(SELECT count(*) FROM extras)"' \
  > "$backup/counts.before"
docker exec "$old_db" sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$backup/planner.dump"
test -s "$backup/planner.dump"
docker exec -i "$old_db" pg_restore --list \
  < "$backup/planner.dump" > "$backup/dump-contents.txt"
```

Обновите код. Восстановите прежнее описание БД из истории проекта и сгенерируйте
постоянный override. Коммит `ce828f4` соответствует старому Compose, с которым
были созданы контейнеры из стандартной установки.

```bash
git pull --ff-only origin main
git show ce828f4:docker-compose.yml > "$backup/docker-compose.old.yml"
cp "$backup/env.before" "$backup/.env"
docker compose -p school-planner-bot \
  -f "$backup/docker-compose.old.yml" \
  config --format json > "$backup/compose.before.json"
test ! -e compose.keep-db.json
python3 scripts/keep-existing-db.py "$backup/compose.before.json"
```

Перед миграцией сравните реквизиты. Значения `DATABASE_USER`,
`DATABASE_PASSWORD`, `DATABASE_NAME` в рабочем `.env` должны соответствовать
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` старого контейнера. Не
присылайте пароль в чаты или логи.

```bash
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$old_db" \
  | grep '^POSTGRES_'
grep '^DATABASE_' .env
```

Добавьте или проверьте в `.env`: `APP_ENV=production`, `BOT_USERNAME` без `@`,
публичный `WEBAPP_URL`. Удалите `WEBAPP_DEV_USER_ID`. Если прокси работает на
этом же сервере, используйте `WEBAPP_BIND_HOST=127.0.0.1`; для внешнего прокси
укажите нужный интерфейс и ограничьте доступ firewall.

Все дальнейшие команды Compose должны содержать оба файла и старое имя проекта:

```bash
dc() {
  docker compose -p school-planner-bot \
    -f docker-compose.yml -f compose.keep-db.json "$@"
}
dc config --quiet
dc build bot webapp migrate
dc run --rm --no-deps migrate
dc up -d --no-deps --force-recreate bot webapp
test "$(dc ps -q db)" = "$old_db"
```

Проверьте количество исходных записей, готовность приложения и логи:

```bash
docker exec "$old_db" sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT (SELECT count(*) FROM users)||'\''|'\''||(SELECT count(*) FROM schedule)||'\''|'\''||(SELECT count(*) FROM extras)"' \
  > "$backup/counts.after"
cmp "$backup/counts.before" "$backup/counts.after"
dc exec -T webapp python -c \
  'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/healthz").read().decode())'
dc ps
dc logs --tail=100 migrate bot webapp
```

После проверки откройте `/today`, `/week` и Mini App под существующим
пользователем. Остановленные контейнер и том пустой PostgreSQL 16 оставьте до
завершения проверки и копирования дампа на отдельное хранилище. Их удаление не
является частью обновления.

Если миграция завершилась ошибкой, не запускайте новый бот. Она транзакционная,
поэтому можно запустить прежние контейнеры `docker start "$old_bot" "$old_web"`
и разобрать ошибку. После успешной миграции откат выполняется восстановлением
`planner.dump` в чистую PostgreSQL 15 и запуском прежнего коммита.

Никогда не подключайте каталог данных PostgreSQL 15 непосредственно к образу
PostgreSQL 16 и не выполняйте `docker compose down -v`, `docker volume prune`
или удаление `pgdata` во время этого обновления.
