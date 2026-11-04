#!/bin/sh
# Пробрасывает :3128 контейнера на прокси за SSH (EGRESS_PROXY на стороне EGRESS_TARGET).
# Ключ и закреплённый ключ сервера лежат в /run/egress (id_ed25519, known_hosts), read-only.
set -eu
: "${EGRESS_TARGET:?Укажите EGRESS_TARGET=<пользователь>@<сервер>}"
exec ssh -NT \
  -o BatchMode=yes -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/run/egress/known_hosts \
  -o GlobalKnownHostsFile=/dev/null -o ExitOnForwardFailure=yes \
  -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=2 \
  -i /run/egress/id_ed25519 \
  -L "0.0.0.0:3128:${EGRESS_PROXY:-127.0.0.1:3128}" \
  "$EGRESS_TARGET"
