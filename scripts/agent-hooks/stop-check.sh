#!/usr/bin/env bash
# Проверяет изменения этой сессии и не повторяет успешный неизменный кандидат.
set -euo pipefail
exec python3 -B "$(dirname "$0")/check-state.py" stop
