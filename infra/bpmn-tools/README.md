# Runtime BPMN tools

Внутренний сервис: `POST /layout {xml}`, `POST /lint {xml}`, `GET /health`. В Compose
порт 3000 не публикуется; backend получает `BPMN_TOOLS_URL=http://bpmn-tools:3000`.
Production не запускается без этого URL, независимо от LLM-провайдера.

Версии закреплены в package-lock: bpmn-auto-layout 2.0.0-alpha.2, bpmnlint 11.14.0,
bpmn-moddle 10.3.1. Лицензии MIT. Проверены реальные библиотечные API установленной версии.
Локальный runtime требует Node >=22.12; Docker использует Node 24.
Проверка `bpmnlint:recommended` идёт по XML, предупреждение сохраняется предупреждением.
Если DI полный, layout возвращает исходный XML точно: ручная геометрия не пересчитывается.
Без/с неполным DI работает bpmn-auto-layout; отсутствие DI для любого flow element — ошибка.
У новых схем задачи расширяются до 160 единиц по ширине и до расчётной высоты полного текста
с запасом под шрифт 12 px. Сетка и контейнеры расширяются вместе с задачами, события и шлюзы
сохраняют стандартный размер. Подпись не сокращается. При полном DI этот этап не применяется:
пользовательская геометрия остаётся байт-в-байт. Canvas gate проверяет реальные SVG-границы
подписей, поскольку серверная оценка размера не заменяет измерение браузерного шрифта.
Никакого неотмеченного запасного алгоритма или успешного результата при сбое нет.

```bash
make setup              # включает npm ci --prefix infra/bpmn-tools
make dev-bpmn-tools     # :3000
# Локальный backend: BPMN_TOOLS_URL=http://127.0.0.1:3000
make test-bpmn-tools    # unit + настоящий HTTP server/worker
make test               # также запускает этот gate
uv run --directory backend python scripts/export_ir_checks.py \
  --tools-url http://127.0.0.1:3000 --output ../reports/tmp/generated-ir
```

Экспортный скрипт проходит источники → записанный JSON адаптера → typed IR → XML → HTTP
layout/официальная XSD/full lint, без live LLM. Сценарии: XOR/default, AND/join, вложенный XOR в AND, цикл,
альтернативные message starts и отдельные нормальные ends параллельных ветвей.
Также проверяются три подробных сценария: энергетическое нарушение (45 узлов), складской
заказ (49) и выпуск сервиса (44). Фикстуры собираются через этот же локальный runtime,
а готовые XML, полные исходные регламенты и записанные IR доступны в `examples/`/`fixtures/`.

Не более двух worker threads одновременно, каждый ограничен 256 MiB старого JS heap.
Третьему запросу — 503; health не ждёт worker. XML максимум 5 MiB, JSON body максимум 8 MiB.
Worker прекращается по отключению клиента или `BPMN_TOOLS_TIMEOUT_SEC` (20 по умолчанию).
Таймаут — 504, некорректный BPMN — 422, сбой worker — 503. Python-адаптер тоже ограничивает
время и размер ответа, отмена не выдаётся за успешную проверку. Зависимости и тесты входят
в make setup/test/verify. Deploy/rollback автоматически добавляет/удаляет sidecar через
существующий `docker compose … --remove-orphans`; persistent данных у sidecar нет.
