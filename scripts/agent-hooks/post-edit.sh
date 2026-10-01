#!/usr/bin/env bash
# Хук агента (Claude Code PostToolUse на Edit/Write/MultiEdit): форматирует и линтит ТОЛЬКО изменённый файл.
# Код выхода 2 = ошибки уходят агенту, и он чинит их сразу, не накапливая мусор.
set -uo pipefail
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$root"

file="$(node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{const j=JSON.parse(s);process.stdout.write(j.tool_input?.file_path??"")}catch{}})')"
[ -n "$file" ] && [ -f "$file" ] || exit 0
rel="${file#"$root"/}"

out=""
case "$rel" in
  frontend/*.ts|frontend/*.tsx|frontend/*.mjs|frontend/*.css|frontend/*.json|scripts/*.mjs)
    out+="$(npx biome check --write --no-errors-on-unmatched "$rel" 2>&1)" || fail=1
    if [[ "$rel" == frontend/src/* ]]; then
      out+="$(cd frontend && node scripts/design-lint.mjs "${rel#frontend/}" 2>&1)" || fail=1
    fi
    ;;
  backend/*.py)
    out+="$(cd backend && uv run ruff format "${rel#backend/}" 2>&1 && uv run ruff check --fix "${rel#backend/}" 2>&1)" || fail=1
    ;;
esac

if [ "${fail:-0}" -ne 0 ]; then
  echo "Проверки для $rel не прошли — исправь до продолжения:" >&2
  echo "$out" | tail -40 >&2
  exit 2
fi
exit 0
