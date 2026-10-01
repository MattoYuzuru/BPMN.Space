#!/usr/bin/env bash
# Полный прогон перед MR. Пишет отчёт reports/verify-<sha>.md (его публикует scripts/mr-report.sh).
# Отчёт имеет смысл только для закоммиченного состояния — иначе sha не соответствует проверенному коду.
set -uo pipefail
cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
  echo "verify: есть незакоммиченные изменения — закоммить их, чтобы отчёт соответствовал sha." >&2
  exit 1
fi

sha="$(git rev-parse --short HEAD)"
branch="$(git rev-parse --abbrev-ref HEAD)"
report="reports/verify-$sha.md"
mkdir -p reports
overall=0

{
  echo "### verify @ \`$sha\` (\`$branch\`)"
  echo
  echo "| Шаг | Результат | Время |"
  echo "|---|---|---|"
} > "$report.rows"

step() {
  local name="$1"; shift
  local start end status
  start=$(date +%s)
  if "$@" > "reports/.verify-$name.log" 2>&1; then status="ok"; else status="FAIL"; overall=1; fi
  end=$(date +%s)
  echo "| $name | $status | $((end - start)) s |" >> "$report.rows"
  echo "verify: $name — $status"
}

step lint make lint
step design-lint make design-lint
step typecheck make typecheck
step tests make test
step contract make contract-check
step build make build
step secrets make secrets
step e2e make e2e

coverage="$(grep -Eo 'TOTAL.*[0-9]+%' reports/.verify-tests.log | grep -Eo '[0-9]+%$' || echo 'n/a')"
{
  cat "$report.rows"
  echo
  echo "Покрытие backend: $coverage. Итог: $([ $overall -eq 0 ] && echo 'все шаги зелёные' || echo 'есть упавшие шаги, логи в reports/.verify-*.log')."
} > "$report"
rm -f "$report.rows"
cat "$report"
exit $overall
