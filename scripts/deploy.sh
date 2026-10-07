#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

deploy_host="${DEPLOY_HOST:-}"
deploy_user="${DEPLOY_USER:-deploy}"
remote_root="${DEPLOY_PATH:-/home/$deploy_user/arkhitektor}"
ref="${1:-}"

if [[ -z "$deploy_host" || -z "$ref" ]]; then
  echo "Использование: DEPLOY_HOST=<IP> [DEPLOY_USER=deploy] scripts/deploy.sh <sha|tag>" >&2
  exit 2
fi
if [[ ! "$deploy_host" =~ ^[A-Za-z0-9.-]+$ || ! "$deploy_user" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  echo "Некорректный DEPLOY_HOST или DEPLOY_USER." >&2
  exit 2
fi
if [[ ! "$remote_root" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
  echo "DEPLOY_PATH должен быть абсолютным путём без пробелов." >&2
  exit 2
fi
if ! command -v ssh >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
  echo "Для деплоя нужны ssh и tar." >&2
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "Рабочая копия не чистая. Сначала сохраните изменения и запустите деплой с commit SHA." >&2
  exit 1
fi

git fetch --quiet origin main:refs/remotes/origin/main
commit="$(git rev-parse --verify "$ref^{commit}")"
if ! git merge-base --is-ancestor "$commit" origin/main; then
  echo "Можно выкладывать только commit, уже входящий в origin/main после Merge Request." >&2
  exit 1
fi

release="$remote_root/releases/$commit"
previous=""
if ssh "$deploy_user@$deploy_host" "test -L '$remote_root/current'"; then
  previous="$(ssh "$deploy_user@$deploy_host" "readlink '$remote_root/current'")"
fi

rollback() {
  echo "Деплой не прошёл. Выполняю откат." >&2
  if [[ -n "$previous" ]]; then
    # Старый код до ADR-0007 не читает packed XML. Восстановить его до смены кода,
    # используя код нового релиза даже при сбое сборки образа (read-only bind mount).
    if ssh "$deploy_user@$deploy_host" "test -f '$release/backend/app/infra/version_maintenance.py' && ! test -f '$previous/backend/app/infra/version_maintenance.py'"; then
      if ! ssh "$deploy_user@$deploy_host" "set -eu; cd '$release'; docker compose --env-file '$remote_root/shared/.env' -p arkhitektor -f compose.yaml -f compose.prod.yaml stop backend; docker compose --env-file '$remote_root/shared/.env' -p arkhitektor -f compose.yaml -f compose.prod.yaml run --rm --no-deps -T -v '$release/backend/app:/app/app:ro' --entrypoint python backend -m app.infra.version_maintenance --restore"; then
        echo "Не удалось восстановить XML для старого релиза. Откат остановлен, данные сохранены; требуется ручное восстановление." >&2
        return 1
      fi
    fi
    ssh "$deploy_user@$deploy_host" "set -eu; ln -sfn '$previous' '$remote_root/current'; cd '$previous'; docker compose --env-file '$remote_root/shared/.env' -p arkhitektor -f compose.yaml -f compose.prod.yaml up -d --build --remove-orphans"
  else
    ssh "$deploy_user@$deploy_host" "cd '$release' && docker compose --env-file '$remote_root/shared/.env' -p arkhitektor -f compose.yaml -f compose.prod.yaml down" || true
  fi
}

# Снимок persistent-данных до переключения релиза и запуска миграций.
# На первой установке previous пустой, поэтому сохранять ещё нечего.
if [[ -n "$previous" ]]; then
  backup_id="$(date -u +%Y%m%dT%H%M%SZ)-$commit"
  backup_dir="$remote_root/backups/$backup_id"
  ssh "$deploy_user@$deploy_host" "set -eu; umask 077; mkdir -p '$backup_dir'; chmod 0700 '$backup_dir'; cd '$previous'; compose='docker compose --env-file $remote_root/shared/.env -p arkhitektor -f compose.yaml -f compose.prod.yaml'; if \$compose config --services | grep -qx db; then \$compose up -d --wait db; \$compose exec -T db sh -c 'pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"' > '$backup_dir/postgres.sql'; \$compose run --rm --no-deps -T --entrypoint tar backend -C /data/uploads -czf - . > '$backup_dir/uploads.tar.gz'; chmod 0600 '$backup_dir/postgres.sql' '$backup_dir/uploads.tar.gz'; echo 'Persistent data backup created: $backup_id'; else echo 'No PostgreSQL service in current release; skipping first-install backup.'; fi"
fi

git archive --format=tar "$commit" | ssh "$deploy_user@$deploy_host" "set -eu; mkdir -p '$release'; tar -xf - -C '$release'"
if ! ssh "$deploy_user@$deploy_host" "set -eu; test -s '$remote_root/shared/.env'; ln -sfn '$release' '$remote_root/current'; cd '$release'; docker compose --env-file '$remote_root/shared/.env' -p arkhitektor -f compose.yaml -f compose.prod.yaml up -d --build --remove-orphans"; then
  rollback
  exit 1
fi

healthy=false
for _ in $(seq 1 40); do
  if ssh "$deploy_user@$deploy_host" "curl -fsS --max-time 3 http://127.0.0.1/health >/dev/null"; then
    healthy=true
    break
  fi
  sleep 3
done

if [[ "$healthy" != true ]]; then
  rollback
  exit 1
fi

echo "Деплой $commit завершён: http://$deploy_host/"
