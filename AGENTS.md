# AGENTS.md

Вход для ИИ-агентов и людей: что за проект, где что лежит, как работать.

## Проект

ИИ-ассистент «Архитектор BPMN-диаграмм» (хакатон «ИИ-ассистенты для энергетики», Интер РАО / Codenrock). Аналитик складывает в проект источники (текст, голос, документы), система задаёт уточняющие вопросы и строит BPMN 2.0 (валиден по XSD, редактируется в bpmn.io).

**Каноничный документ архитектуры и плана:** [`docs/rfc/0001-architecture.md`](docs/rfc/0001-architecture.md). Правила генерации — [`docs/backend/generation-quality.md`](docs/backend/generation-quality.md). Общий план — GitLab #1–#6, первая очередь качества — #18–#23, дальнейшие задачи — #17 и #24–#34. Воспроизведение и модель бизнес-времени — [`RFC-0003`](docs/rfc/0003-process-playback-and-timing.md).

Сверка приоритетов и оставшихся границ BPMN — [`docs/research/product-priorities-2026-10.md`](docs/research/product-priorities-2026-10.md).
Открытие, генерация, сохранение ручного XML и воспроизведение имеют разные поднаборы;
не объявляйте поддержку типа только по наличию его в палитре bpmn-js. Полноценные ревизии
оснований (#34) и восстановление версии (#30) ещё не следует считать реализованными.
Компактное хранение вошло в `main` (`9e0d7a8`): [ADR-0007](docs/adr/0007-compact-version-storage.md).
Оно не является восстановлением версии или ревизиями доказательств.
Полнота контекста, независимая смысловая сверка и повтор запуска после рестарта —
[ADR-0008](docs/adr/0008-evidence-semantic-review-and-recovery.md); это не OCR и не распределённая очередь.

Удаление и выход участника: [ADR-0009](docs/adr/0009-project-deletion-and-leaving.md).
`DELETE /projects/{id}` зависит от роли: owner удаляет для всех, участник выходит сам.

## Карта

| Путь | Что |
|---|---|
| `backend/` | FastAPI, Python 3.13, uv. Слои `api → services → (llm, ingest, infra) → domain` (проверяет import-linter). PostgreSQL/Alembic описаны в `docs/backend/persistence.md`; оставшиеся заглушки — `docs/backend/mock.md` |
| `backend/app/llm/{question_analysis,graph_generation}.py`, `domain/bpmn/{ir,compiler,importer,manual,xsd}.py` | порционная сверка вопросов с проверкой оснований, граф IR v1, компилятор, приоритет ручных правок и offline XSD — `docs/backend/generation-quality.md` |
| `infra/bpmn-tools/`, `backend/app/infra/bpmn_tools.py` | внутренний Node layout/lint и HTTP-адаптер; точные пределы и команды — `infra/bpmn-tools/README.md` |
| `frontend/src/entities/{session,share}`, маршруты `/login`, `/share/$token` | аккаунты и общий доступ: правила — `docs/backend/auth-and-sharing.md`, UI-паттерны — стайлгайд §16 |
| `frontend/src/features/onboarding`, `widgets/onboarding-root`, `shared/lib/{tour-anchors,onboarding-signals}.ts` | обучение: движок тура, сценарий из 11 шагов, приветствие, подсказки-указатели, якоря `data-tour`, сигналы приложения — `docs/frontend/onboarding.md`, паттерн — стайлгайд §10 |
| `backend/app/{domain,services,api/v1}/onboarding.py`, `fixtures/samples*` | онбординг: тур, чек-лист «Начало работы», учебные материалы «Примеры»; правила — `docs/backend/onboarding.md` |
| `backend/migrations/` | Alembic-миграции PostgreSQL; правила и сохраняемые сущности — `docs/backend/persistence.md` |
| `backend/app/fixtures/` | демо-данные mock-а: тексты, BPMN-схемы, записанные ответы модели (`make fixtures` пересобирает схемы) |
| `examples/` | примеры входа и выхода для жюри (копии фикстур) |
| `frontend/` | React 19 + Vite + TS, TanStack Router/Query, Tailwind v4, Radix, bpmn-js |
| `frontend/src/widgets/diagram-editor` | BPMN, локальное воспроизведение, мини-карта и экспорт — `docs/frontend/diagram-editor.md`; скорость анимации не задаёт длительности бизнеса |
| `frontend/src/features/project-collaboration`, `backend/app/{api/v1,services}/collaboration.py` | WebSocket-комната, курсоры и защита сохранений через `base_version_id` — `docs/rfc/0002-realtime-collaboration.md` |
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
make dev-bpmn-tools # :3000; backend: BPMN_TOOLS_URL=http://localhost:3000
make check-fast   # линт + design-lint + типы (после каждой правки)
make check        # всё: + тесты (backend cov ≥80%) + контракт + сборка (pre-push)
make test-bpmn-tools # настоящий Node layout/lint; также входит в make check/verify
make gen-api      # после изменения API: OpenAPI + TS-типы
make fixtures     # пересобрать BPMN-фикстуры и examples/ (Node, XSD, bpmnlint)
make e2e          # Playwright против Docker-стека; E2E_BASE_URL задаёт уже запущенный стенд
make e2e-diagram  # настоящий BPMN canvas: воспроизведение, шлюзы, экспорт, мини-карта; Vite без backend
make eval-complex # три подробных регламента без платных вызовов; сначала dev-bpmn-tools
make verify       # перед MR: check + e2e + секреты → reports/verify-<sha>.md
make mr-report    # отчёт verify комментарием в MR
make deploy-env   # передать production-переменные из локального .env на VM по SSH
make deploy       # задеплоить commit из main после MR и make verify
```

Деплой: сначала прочитайте [`docs/deployment.md`](docs/deployment.md). Production выкладывается только из `origin/main` по SHA, секреты хранятся отдельно в `/home/deploy/arkhitektor/shared/.env` на VM.

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
