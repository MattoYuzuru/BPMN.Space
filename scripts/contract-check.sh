#!/usr/bin/env bash
# Проверка контракта API между backend и frontend.
# 1) OpenAPI, выгруженный из кода backend, совпадает с docs/api/openapi.json;
# 2) TS-типы фронтенда сгенерированы из этого же файла.
# Если нет — кто-то поменял API и не перегенерировал контракт: `make gen-api` и закоммитить.
set -euo pipefail
cd "$(dirname "$0")/.."

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

(cd backend && uv run python -m app.openapi_export) > "$tmp/openapi.json"
npx --workspace frontend openapi-typescript "$PWD/docs/api/openapi.json" -o "$tmp/schema.gen.ts" --silent >/dev/null

fail=0
if ! diff -q "$tmp/openapi.json" docs/api/openapi.json >/dev/null; then
  echo "contract-check: docs/api/openapi.json устарел относительно кода backend." >&2
  diff -u docs/api/openapi.json "$tmp/openapi.json" | head -40 >&2 || true
  fail=1
fi
if ! diff -q "$tmp/schema.gen.ts" frontend/src/shared/api/schema.gen.ts >/dev/null; then
  echo "contract-check: frontend/src/shared/api/schema.gen.ts не соответствует docs/api/openapi.json." >&2
  fail=1
fi
if [ "$fail" -ne 0 ]; then
  echo "Исправление: make gen-api && git add docs/api/openapi.json frontend/src/shared/api/schema.gen.ts" >&2
  exit 1
fi
echo "contract-check: контракт согласован."
