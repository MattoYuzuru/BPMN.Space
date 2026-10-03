#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ENV_FILE:-$repo_root/.env}"
deploy_host="${DEPLOY_HOST:-}"
deploy_user="${DEPLOY_USER:-deploy}"
remote_root="${DEPLOY_PATH:-/home/$deploy_user/arkhitektor}"

if [[ -z "$deploy_host" ]]; then
  echo "Задайте DEPLOY_HOST с адресом VM." >&2
  exit 1
fi
if [[ ! "$deploy_host" =~ ^[A-Za-z0-9.-]+$ || ! "$deploy_user" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  echo "Некорректный DEPLOY_HOST или DEPLOY_USER." >&2
  exit 1
fi
if [[ ! -f "$env_file" ]]; then
  echo "Не найден файл конфигурации $env_file." >&2
  exit 1
fi
if [[ ! "$remote_root" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
  echo "DEPLOY_PATH должен быть абсолютным путём без пробелов." >&2
  exit 1
fi

# .env — доверенный shell-формат проекта. Значения не печатаются и не попадают в Git.
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

: "${DEEPSEEK_API_KEY:?В .env не задан DEEPSEEK_API_KEY}"
: "${DEEPGRAM_API_KEY:?В .env не задан DEEPGRAM_API_KEY}"
: "${POSTGRES_PASSWORD:?В .env задайте отдельный POSTGRES_PASSWORD для production PostgreSQL}"
if [[ "$POSTGRES_PASSWORD" == "local-dev-only" || ${#POSTGRES_PASSWORD} -lt 32 ]]; then
  echo "POSTGRES_PASSWORD должен быть production-секретом длиной не менее 32 символов." >&2
  exit 1
fi
for key in "$DEEPSEEK_API_KEY" "$DEEPGRAM_API_KEY" "$POSTGRES_PASSWORD"; do
  if [[ ! "$key" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Ключ содержит символы, требующие ручной настройки; файл на сервер не загружен." >&2
    exit 1
  fi
done

temporary_file="$(mktemp)"
trap 'rm -f "$temporary_file"' EXIT
chmod 0600 "$temporary_file"
cat >"$temporary_file" <<EOF
APP_ENV=production
WEB_PORT=80
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL=${DEEPSEEK_BASE_URL:-https://api.deepseek.com}
DEEPSEEK_MODEL=${DEEPSEEK_MODEL:-deepseek-flash}
STT_PROVIDER=deepgram
DEEPGRAM_API_KEY=$DEEPGRAM_API_KEY
POSTGRES_DB=${POSTGRES_DB:-arkhitektor}
POSTGRES_USER=${POSTGRES_USER:-arkhitektor}
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
EOF

ssh "$deploy_user@$deploy_host" "umask 077; install -d -m 0750 '$remote_root/shared'; cat > '$remote_root/shared/.env.new' && chmod 0600 '$remote_root/shared/.env.new' && mv '$remote_root/shared/.env.new' '$remote_root/shared/.env'" <"$temporary_file"
echo "Серверная конфигурация обновлена; значения секретов не выводились."
