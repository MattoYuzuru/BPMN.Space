#!/usr/bin/env bash
# Публикует отчёт verify для текущего коммита комментарием в открытый MR текущей ветки.
# Токен: GITLAB_TOKEN из окружения или из .env (не печатается).
set -euo pipefail
cd "$(dirname "$0")/.."

GITLAB_HOST="${GITLAB_HOST:-https://git.codenrock.com}"
PROJECT="${GITLAB_PROJECT:-codenrock%2Fii-assistenty%2Fpodayte-tokenov-pzhpzh%2Farkhitektor-bpmn-diagramm}"

if [ -z "${GITLAB_TOKEN:-}" ] && [ -f .env ]; then
  set -a; . ./.env; set +a
fi
: "${GITLAB_TOKEN:?Нужен GITLAB_TOKEN (PAT со scope api) в окружении или .env}"

sha="$(git rev-parse --short HEAD)"
branch="$(git rev-parse --abbrev-ref HEAD)"
report="reports/verify-$sha.md"
[ -f "$report" ] || { echo "Нет $report — сначала make verify" >&2; exit 1; }

api() { curl -sS --retry 4 --retry-all-errors -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$@"; }

iid="$(api "$GITLAB_HOST/api/v4/projects/$PROJECT/merge_requests?state=opened&source_branch=$branch" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["iid"] if d else "")')"
[ -n "$iid" ] || { echo "Нет открытого MR для ветки $branch" >&2; exit 1; }

python3 -c 'import json,sys; print(json.dumps({"body": open(sys.argv[1]).read()}))' "$report" \
  | api -X POST -H "Content-Type: application/json" --data-binary @- \
    "$GITLAB_HOST/api/v4/projects/$PROJECT/merge_requests/$iid/notes" >/dev/null
echo "Отчёт $report опубликован в MR !$iid"
