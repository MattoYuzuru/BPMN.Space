#!/usr/bin/env bash
# Хук агента (Claude Code Stop): перед завершением ответа прогоняет `make check-fast`,
# если в рабочей копии есть изменения кода. Повторно не срабатывает (stop_hook_active), чтобы не зациклиться.
set -uo pipefail
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$root"

active="$(node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{process.stdout.write(String(JSON.parse(s).stop_hook_active??false))}catch{process.stdout.write("false")}})')"
[ "$active" = "true" ] && exit 0
[ -n "$(git status --porcelain -- frontend backend scripts)" ] || exit 0

if ! out="$(make check-fast 2>&1)"; then
  echo "make check-fast упал после твоих изменений. Исправь ошибки (фронтенд и бэкенд проверяются вместе):" >&2
  echo "$out" | grep -vE '^make(\[[0-9]+\])?: (Entering|Leaving)' | tail -60 >&2
  exit 2
fi
exit 0
