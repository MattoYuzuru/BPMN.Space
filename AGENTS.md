# AGENTS.md

Вход для ИИ-агентов и людей: что за проект, где что лежит, как работать.

## Проект

ИИ-ассистент «Архитектор BPMN-диаграмм» (хакатон «ИИ-ассистенты для энергетики», Интер РАО / Codenrock). Аналитик складывает в проект источники (текст, голос, документы), система задаёт уточняющие вопросы и строит BPMN 2.0 (валиден по XSD, редактируется в bpmn.io).

**Каноничный документ архитектуры и плана:** [`docs/rfc/0001-architecture.md`](docs/rfc/0001-architecture.md). Задачи — GitLab Issues #1–#6.

## Карта

| Путь | Что |
|---|---|
| `backend/` | FastAPI, Python 3.13, uv. Слои `api → services → (llm, ingest, infra) → domain` (проверяет import-linter). PostgreSQL/Alembic описаны в `docs/backend/persistence.md`; оставшиеся заглушки — `docs/backend/mock.md` |
| `backend/migrations/` | Alembic-миграции PostgreSQL; правила и сохраняемые сущности — `docs/backend/persistence.md` |
| `backend/app/fixtures/` | демо-данные mock-а: тексты, BPMN-схемы, записанные ответы модели (`make fixtures` пересобирает схемы) |
| `examples/` | примеры входа и выхода для жюри (копии фикстур) |
| `frontend/` | React 19 + Vite + TS, TanStack Router/Query, Tailwind v4, Radix, bpmn-js |
| `frontend/scripts/design-lint.mjs` | правила дизайн-системы (нативные контролы, сырые цвета, символы вместо иконок…) |
| `docs/api/openapi.json` | контракт API, генерируется из backend (`make gen-api`) |
| `frontend/src/shared/api/schema.gen.ts` | TS-типы из контракта (генерируются, руками не править) |
| `docs/` | RFC, ADR, стайлгайд и архитектура фронтенда (`docs/frontend/`), бэкенда (`docs/backend/`) |
| `scripts/` | `contract-check.sh`, `verify.sh`, `mr-report.sh`, `agent-hooks/` |
| `compose.yaml`, `infra/caddy/` | локальный стек: `make up` → http://localhost:8080 |
| `docs/deployment.md`, `scripts/deploy.sh` | ручной деплой проверенного commit SHA на демо-VM; GitLab CI/CD не используется |

## Команды

```bash
make setup        # npm ci + uv sync + chromium + git-хуки
make up           # стек в Docker → http://localhost:8080
make db-upgrade   # вручную применить миграции к локальной PostgreSQL
make dev-backend  # :8000 с автоперезагрузкой
make dev-frontend # :5173, /api проксируется на :8000
make check-fast   # линт + design-lint + типы (после каждой правки)
make check        # всё: + тесты (backend cov ≥80%) + контракт + сборка (pre-push)
make gen-api      # после изменения API: OpenAPI + TS-типы
make fixtures     # пересобрать BPMN-фикстуры и examples/ (Node, XSD, bpmnlint)
make e2e          # Playwright против Docker-стека; E2E_BASE_URL задаёт уже запущенный стенд
make verify       # перед MR: check + e2e + секреты → reports/verify-<sha>.md
make mr-report    # отчёт verify комментарием в MR
make deploy-env   # передать production-переменные из локального .env на VM по SSH
make deploy       # задеплоить commit из main после MR и make verify
```

Деплой: сначала прочитайте [`docs/deployment.md`](docs/deployment.md). Production выкладывается только из `origin/main` по SHA, секреты хранятся отдельно в `/opt/arkhitektor/shared/.env` на VM.

## Правила

- **Проверяем всё, а не только «свою» часть.** Pre-push и хук агента гоняют фронтенд, бэкенд и контракт вместе. Сломал соседнюю часть — чини её в том же MR.
- Прямой push в `main` запрещён: ветки `feature/*`, `fix/*`, `docs/*`, `chore/*` → Merge Request (`Closes #N`).
- Изменил API → `make gen-api` и закоммить оба сгенерированных файла, иначе `contract-check` уронит push.
- Конфигурация — только `backend/app/config.py` и `.env.example`. Секреты — только в `.env`; не печатать их.
- XML BPMN генерирует код, а не LLM; LLM возвращает JSON IR (RFC §5).
- Фронтенд — только из дизайн-системы (`frontend/src/shared/ui`), правила — `docs/frontend/styleguide.md`. Нарушения ловит `design-lint`.
- Интерфейс — на русском. Комментарии в коде и документация — на русском; идентификаторы — на английском.
- Definition of Done — в скилле `pickup-task`.

## Хуки

- Git (lefthook, ставится при `npm ci`): pre-commit — biome, design-lint, ruff, secretlint по изменённым файлам; pre-push — `make check`.
- Claude Code (`.claude/settings.json`): после правки файла — его форматирование и линт; перед завершением ответа — `make check-fast`.
- Другие агенты: после правок запускайте `make check-fast`, перед MR — `make verify`.

## Скиллы (`.claude/skills/`)

| Скилл | Когда |
|---|---|
| `pickup-task` | взять задачу, собрать контекст, DoD |
| `verify` | все гейты + отчёт в MR |
| `cleaner` | light/hard уборка кода и документации (основа — плагин `cleaner-agent` из [yuzuru-skills](https://github.com/MattoYuzuru/yuzuru-skills)) |
| `new-endpoint` | новый/изменённый эндпоинт по слоям |
| `prompt-eval` | промпты, модели, golden set |
| `e2e-agent` | сквозной сценарий в браузере на локальном стеке |
| `deploy` | деплой на VM (только по явной команде человека) |
| `adr` | ADR / RFC |

Агентам без поддержки скиллов Claude Code: читайте `.claude/skills/<name>/SKILL.md` как инструкцию.
