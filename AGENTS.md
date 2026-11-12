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

Длинные документы, XLSX/PPTX, страницы PDF без текста и расшифровка записей:
[ADR-0012](docs/adr/0012-long-documents-and-media.md), пределы — `docs/backend/generation-quality.md`.

Реализованы персональные токены `bps_…` и MCP-сервер `/mcp` для внешних агентов
([RFC-0007](docs/rfc/0007-external-agents-mcp.md), [mcp.md](docs/backend/mcp.md)) — шаги 1–2;
шаг 3 (роль ссылки `reviewer`, область-дорожки, промпт и токен агента, журнал активности) —
бэкенд готов, UI проверки — фронтовая волна. Реализованы справочник
возможностей, профиль запуска, оценка стоимости, учёт кеш-токенов, бюджет прогона и
технические вопросы ([RFC-0005](docs/rfc/0005-full-model-capacity-and-cost.md) шаги 1–5,
[RFC-0006](docs/rfc/0006-tools-connectors-and-derived-sources.md) шаг 2). Инструменты по
ключам пользователя: шаг 1 — обобщённые ключи по типам задач, маршрутизация с классами
ошибок и распознавание речи на ключах пользователя; шаги 4–5 RFC-0006 — OCR страниц-сканов
моделью с чтением PDF, кадры видео и описание экрана (`vision`), общая лента и краткое
содержание, профили обработки и оценка, плеер с HTTP Range и таймкодами
([media-and-derived-sources.md](docs/backend/media-and-derived-sources.md)); шаг 6 частично —
веб-поиск (Tavily, Brave, Exa) и чтение страниц (Jina Reader, Firecrawl), сервис инструментов
агентного режима и каталог провайдеров ([web-tools.md](docs/backend/web-tools.md)); роль ссылки
`reviewer`, промпт и токен агента по ссылке, журнал активности
([auth-and-sharing.md](docs/backend/auth-and-sharing.md), [mcp.md](docs/backend/mcp.md)).
Реализован шаг 1 агентного режима ([RFC-0004](docs/rfc/0004-agent-mode.md),
[agent-mode.md](docs/backend/agent-mode.md)): `LlmClient.complete_with_tools`, инструменты
только-чтения (FTS `russian`, миграция `0024_agent_search`), цикл до проверяемого `submit`,
бюджет ходов/токенов/денег и восстановление; включается `LLM_AGENT_MODE=true` и
`RunProfile.mode=agent` только для моделей с инструментами. Отдельные ключи/адаптеры `vision` и
`ocr` (Mistral/Yandex), `video_understanding` и озвучка остаются контрактами: vision и OCR
выполняет модель ключа `llm`. Предложено, не реализовано: шаг 7 RFC-0006 (ревизии производных),
OAuth для MCP, UI проверки коллеги и агентского режима (фронтовая волна), рабочие модели
`worker`/`delegate`.

Сессии правок и контрольные точки (автосохранения сливаются в версию): [ADR-0010](docs/adr/0010-editing-sessions-and-checkpoints.md).
Удаление и выход участника: [ADR-0009](docs/adr/0009-project-deletion-and-leaving.md).
`DELETE /projects/{id}` зависит от роли: owner удаляет для всех, участник выходит сам.

## Карта

| Путь | Что |
|---|---|
| `backend/` | FastAPI, Python 3.13, uv. Слои `api → services → (llm, ingest, infra) → domain` (проверяет import-linter). PostgreSQL/Alembic описаны в `docs/backend/persistence.md`; оставшиеся заглушки — `docs/backend/mock.md` |
| `backend/app/llm/{question_analysis,graph_generation}.py`, `domain/bpmn/{ir,compiler,importer,manual,xsd}.py` | порционная сверка вопросов с проверкой оснований, граф IR v1, компилятор, приоритет ручных правок и offline XSD — `docs/backend/generation-quality.md` |
| `backend/app/llm/{agent,tools,budget}.py`, `services/agent_run.py`, миграция `0024_agent_search` | агентный режим RFC-0004: `complete_with_tools`, инструменты `list_sources`/`read_source`/`search_sources`/`list_questions`/`propose_question`/`check_graph`/`submit`, цикл с бюджетом ходов и восстановлением — `docs/backend/agent-mode.md` |
| `infra/bpmn-tools/`, `backend/app/infra/bpmn_tools.py` | внутренний Node layout/lint и HTTP-адаптер; точные пределы и команды — `infra/bpmn-tools/README.md` |
| `frontend/src/entities/{session,share}`, маршруты `/login`, `/share/$token` | аккаунты и общий доступ: правила — `docs/backend/auth-and-sharing.md`, UI-паттерны — стайлгайд §16 |
| `frontend/src/features/onboarding`, `widgets/onboarding-root`, `shared/lib/{tour-anchors,onboarding-signals}.ts` | обучение: движок тура, сценарий из 11 шагов, приветствие, подсказки-указатели, якоря `data-tour`, сигналы приложения — `docs/frontend/onboarding.md`, паттерн — стайлгайд §10 |
| `backend/app/{domain,services,api/v1}/onboarding.py`, `fixtures/samples*` | онбординг: тур, чек-лист «Начало работы», учебные материалы «Примеры»; правила — `docs/backend/onboarding.md` |
| `backend/app/llm/{client,factory,pipeline,anthropic,openai,openai_compatible,openai_responses,net_guard}.py`, `services/{model_resolver,credentials,llm_credentials}.py`, `infra/crypto.py`, `api/v1/{llm_credentials,credentials}.py`, `frontend/src/{entities/llm-credential,features/llm-credentials,features/model-picker}`, маршрут `/settings` | модельно-независимый запуск: свои ключи пользователя (шифруются), провайдеры Anthropic/OpenAI/совместимые (Chat Completions или Responses, `llm/openai_responses.py`), выбор модели на прогон, защита от SSRF — [ADR-0011](docs/adr/0011-user-llm-credentials.md), [ADR-0013](docs/adr/0013-responses-wire-protocol.md), `docs/backend/подключение-провайдеров.md` |
| `backend/app/mcp/`, `backend/app/{domain,services,api/v1}/api_tokens.py`, `infra/repositories/api_tokens_sql.py` | внешние агенты: персональные токены `bps_…` (вход по `Authorization: Bearer` в REST) и MCP-сервер `/mcp` (инструменты, ресурсы, подсказки, провенанс «через агента») — [RFC-0007](docs/rfc/0007-external-agents-mcp.md), [mcp.md](docs/backend/mcp.md), [auth-and-sharing.md](docs/backend/auth-and-sharing.md) |
| `backend/app/services/review.py`, `backend/app/api/v1/sharing.py`, `frontend/src/entities/share`, `frontend/src/features/share-project` | проверка коллегой (RFC-0007, шаг 3): ссылка `reviewer` с областью-дорожками, готовый промпт для агента, токен агента по ссылке, журнал активности — [auth-and-sharing.md](docs/backend/auth-and-sharing.md), [mcp.md](docs/backend/mcp.md) |
| `backend/app/{domain,services}/capabilities*.py`, `services/{capability_router,credentials,capability_incidents,tool_catalog,web_tools}.py`, `ingest/adapters/`, миграция `0020_user_credentials` | ключи по типам задач и маршрутизация инструментов (RFC-0006 шаги 1, 6): возможности, перебор по приоритету, классы ошибок, предохранитель, STT и веб-поиск/чтение страниц на ключах пользователя, каталог провайдеров и `GET /me/tool-catalog` — [RFC-0006](docs/rfc/0006-tools-connectors-and-derived-sources.md), [web-tools.md](docs/backend/web-tools.md), [каталог провайдеров](docs/research/tool-providers-2026-11.md) |
| `backend/app/llm/multimodal.py`, `ingest/{frames,pdf}.py`, `services/{media_derivation,media_estimate}.py`, `domain/media.py` | волна 3 RFC-0006 шаги 4–5: `complete_vision`/`complete_document` в порте `LlmClient`, OCR страниц-сканов моделью с чтением PDF, кадры видео (смена сцены + dhash без Pillow), производные узлы «ключевые кадры/описание экрана/общая лента/краткое содержание», профили обработки и оценка, `GET /sources/{id}/media` с HTTP Range и `GET /sources/{id}/segments` — [media-and-derived-sources.md](docs/backend/media-and-derived-sources.md) |
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
| `docs/deployment.md`, `scripts/deploy.sh` | ручной деплой проверенного commit SHA на демо-VM; GitLab CI/CD не используется; проверки на GitHub Actions не деплоят |

## Команды

```bash
make setup        # npm ci + uv sync + chromium + git-хуки
make up           # стек в Docker → http://localhost:8080
make db-upgrade   # вручную применить миграции к локальной PostgreSQL
make dev-backend  # :8000 с автоперезагрузкой
make dev-frontend # :5173, /api проксируется на :8000
make dev-bpmn-tools # :3000; backend: BPMN_TOOLS_URL=http://localhost:3000
make check-fast   # линт + design-lint + типы (после изменения кода)
make check        # всё: + тесты (backend cov ≥80%) + контракт + сборка (pre-push)
make test-bpmn-tools # настоящий Node layout/lint; также входит в make check/verify
make gen-api      # после изменения API: OpenAPI + TS-типы
make fixtures     # пересобрать BPMN-фикстуры и examples/ (Node, XSD, bpmnlint)
make e2e          # Playwright против Docker-стека; E2E_BASE_URL задаёт уже запущенный стенд
make e2e-diagram  # настоящий BPMN canvas: воспроизведение, шлюзы, экспорт, мини-карта; Vite без backend
make eval-complex # три подробных регламента без платных вызовов; сначала dev-bpmn-tools
make verify       # перед MR с кодом: check + e2e + секреты → reports/verify-<sha>.md
make mr-report    # отчёт verify комментарием в MR
make deploy-env   # передать production-переменные из локального .env на VM по SSH
make deploy       # задеплоить commit из main после MR и make verify
```

Деплой: сначала прочитайте [`docs/deployment.md`](docs/deployment.md). Production выкладывается только из `origin/main` по SHA, секреты хранятся отдельно в `/home/deploy/arkhitektor/shared/.env` на VM.

## Правила

- **Продуктовые изменения проверяем целиком.** Pre-push гоняет фронтенд, бэкенд и контракт вместе для кода/runtime и неизвестного scope. Только документация и агентские хуки проходят точечные проверки по [правилам хуков](scripts/agent-hooks/README.md). Сломал соседнюю часть — чини её в том же MR.
- Прямой push в `main` запрещён: ветки `feature/*`, `fix/*`, `docs/*`, `chore/*` → Merge Request (`Closes #N`).
- Изменил API → `make gen-api` и закоммить оба сгенерированных файла, иначе `contract-check` уронит push.
- Конфигурация — только `backend/app/config.py` и `.env.example`. Секреты — только в `.env`; не печатать их.
- XML BPMN генерирует код, а не LLM; LLM возвращает JSON IR (RFC §5).
- Фронтенд — только из дизайн-системы (`frontend/src/shared/ui`), правила — `docs/frontend/styleguide.md`. Нарушения ловит `design-lint`.
- Интерфейс — на русском. Комментарии в коде и документация — на русском; идентификаторы — на английском.
- Definition of Done — в скилле `pickup-task`.

## Хуки

- Git (lefthook, ставится при `npm ci`): pre-commit — biome, design-lint, ruff, secretlint по изменённым файлам; pre-push выбирает точечные проверки документации/agent hooks либо полный `make check` по публикуемому delta.
- Claude Code (`.claude/settings.json`): после правки файла — его форматирование и линт; перед завершением ответа — `make check-fast` для новых изменений этой сессии, с кешем успешного неизменного кандидата. Чтение и ранее оставленный dirty checkout сами по себе gate не запускают.
- GitHub Actions (`.github/workflows/ci.yml`): на push в `main` и pull request гоняет lint, тесты backend (+ PostgreSQL), frontend, bpmn-tools, контракт, секреты и сборку Docker-стека со smoke-проверкой `/health`. Playwright e2e — отдельно (`e2e.yml`, вручную и раз в сутки). Деплой остаётся ручным.
- Другие агенты: после изменения кода запускайте `make check-fast`, перед MR с кодом — `make verify`. Для документации/agent hooks достаточно [точечных проверок](scripts/agent-hooks/README.md).

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
