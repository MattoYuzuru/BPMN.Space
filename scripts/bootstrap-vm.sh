#!/usr/bin/env bash
set -Eeuo pipefail

# Run once on a fresh Ubuntu 24.04 VM as root. Add each developer's public key
# to /home/deploy/.ssh/authorized_keys afterwards; never copy private keys here.
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запустите скрипт от root." >&2
  exit 1
fi

deploy_user="${DEPLOY_USER:-deploy}"
if [[ ! "$deploy_user" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  echo "Некорректное имя пользователя DEPLOY_USER." >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "Скрипт рассчитан на Ubuntu/Debian с apt-get." >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 rsync curl ca-certificates
systemctl enable --now docker

if ! id "$deploy_user" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$deploy_user"
fi
usermod -aG docker "$deploy_user"

home_dir="$(getent passwd "$deploy_user" | cut -d: -f6)"
install -d -m 0700 -o "$deploy_user" -g "$deploy_user" "$home_dir/.ssh"
remote_root="$(getent passwd "$deploy_user" | cut -d: -f6)/arkhitektor"
install -d -m 0750 -o "$deploy_user" -g "$deploy_user" "$remote_root/shared"
install -d -m 0750 -o "$deploy_user" -g "$deploy_user" "$remote_root/releases"

authorized_keys="$home_dir/.ssh/authorized_keys"
touch "$authorized_keys"
chmod 0600 "$authorized_keys"
chown "$deploy_user:$deploy_user" "$authorized_keys"
echo "VM готова. SSH-доступ настроен для пользователя $deploy_user."
echo "Добавьте публичные ключи команды в $authorized_keys с правами 0600."
echo "Каталог релизов: $remote_root"
echo "Важно: группа docker даёт полномочия уровня root; добавляйте туда только тех, кому доверяете управление сервером."
