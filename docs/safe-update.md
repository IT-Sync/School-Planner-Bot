# Обновление действующего сервера с сохранением БД

Этот порядок сохраняет текущий контейнер PostgreSQL, его версию, каталог/том и имя Compose-проекта. Обновление PostgreSQL 15 → 16 здесь не выполняется. Все команды выполняйте в одной Bash-сессии из каталога проекта. При любой ошибке остановитесь; не переходите к запуску следующих команд вручную.

## 1. До git pull: сохранить конфигурацию и резервную копию

```bash
cd /opt/pybot/School-Planner-Bot
set -euo pipefail
umask 077
backup="$PWD/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
# При повторном обновлении сохраняем уже закреплённую конфигурацию.
dc() {
  if [ -f compose.keep-db.json ]; then
    docker compose -f docker-compose.yml -f compose.keep-db.json "$@"
  else
    docker compose "$@"
  fi
}
dc config --format json > "$backup/compose.before.json"
cp .env "$backup/env.before"
git rev-parse HEAD > "$backup/git-before.txt"
db_id="$(dc ps -q db)"
test -n "$db_id"
docker inspect "$db_id" > "$backup/db-container.json"
# Останавливаем все записи со стороны приложения, саму БД не трогаем.
dc stop bot webapp
docker exec "$db_id" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup/planner.dump"
test -s "$backup/planner.dump"
docker exec -i "$db_id" pg_restore --list < "$backup/planner.dump" > "$backup/dump-contents.txt"
printf 'Резервная копия: %s\n' "$backup"
```

Если другие приложения тоже пишут в эту базу, остановите их на время обновления. Копия сделана после остановки бота и веба; исходный каталог БД остаётся на месте. Скопируйте каталог резервной копии также на отдельное хранилище.

## 2. Обновить код и закрепить существующую БД

```bash
git pull --ff-only origin main
if [ ! -f compose.keep-db.json ]; then
  python3 scripts/keep-existing-db.py "$backup/compose.before.json"
fi
# С этого места всегда используем сохранённую конфигурацию сервера.
dc() { docker compose -f docker-compose.yml -f compose.keep-db.json "$@"; }
dc config --quiet
```

Не заменяйте `.env` примером. Сохраните прежние `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_NAME`, `BOT_TOKEN` и `WEBAPP_URL`; `DATABASE_PORT` внутри Docker — 5432. В старом стандартном Compose реквизиты были `planner/planner/planner`. Пользовательские значения должны совпадать с действующей БД. Для рабочего запуска задайте `APP_ENV=production`, удалите `WEBAPP_DEV_USER_ID`, заполните `BOT_USERNAME` без `@`. Режим production теперь запрещает обход авторизации через dev-ID.

Новая конфигурация по умолчанию публикует веб только на loopback. Если обратный прокси находится на другом сервере и ранее обращался к порту 11002 по сети, сохраните в `.env` нужный `WEBAPP_BIND_HOST` (IP интерфейса; `0.0.0.0` — все интерфейсы) и ограничьте доступ межсетевым экраном.

`compose.keep-db.json` содержит исходные параметры базы, включая пароль. Файл создаётся с правами 600, исключён из Git и Docker-контекста. Храните его вместе с конфигурацией сервера. При последующих обновлениях используйте Compose с этим файлом; обычный `docker compose up` без него может выбрать другой проект и другое хранилище.

## 3. Пересобрать, применить миграции, запустить

```bash
dc build bot webapp migrate
# --no-deps не позволяет Compose пересоздать PostgreSQL.
dc run --rm --no-deps migrate
dc up -d --no-deps --force-recreate bot webapp
# Проверяем, что это тот же контейнер БД.
test "$(dc ps -q db)" = "$db_id"
dc exec -T webapp python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/healthz").read().decode())'
dc ps
dc logs --tail=80 bot webapp
```

Проверьте свои существующие уроки и кружки через Mini App и `/today`. Миграция переносит данные транзакционно и сохраняет исходные таблицы как `legacy_schedule` и `legacy_extras`. Если миграция завершается ошибкой, приложение не запускайте: сначала устраните причину. Не восстанавливайте дамп поверх непустой рабочей базы; для отката используйте отдельную базу и сохранённую версию приложения.

**Не выполняйте `docker compose down -v`, `docker volume prune` или удаление `pgdata`.** Для этого обновления они не нужны.

## Последующие обновления

Повторяйте резервное копирование из первого блока перед каждым обновлением с миграциями. Для изменения только скриптов без миграции, с уже сохранённым `compose.keep-db.json`:

```bash
git pull --ff-only origin main
docker compose -f docker-compose.yml -f compose.keep-db.json build bot webapp
docker compose -f docker-compose.yml -f compose.keep-db.json up -d --no-deps --force-recreate bot webapp
```
