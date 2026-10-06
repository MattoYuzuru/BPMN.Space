# Фронтенд: документация

| Документ | О чём |
|---|---|
| [architecture.md](architecture.md) | Экраны, слои, данные (ключи запросов, SSE, оптимистичные обновления), ленивость и бюджет, как добавить экран |
| [styleguide.md](styleguide.md) | Гайдбук дизайн-системы: принципы, палитра, типографика, движение, иконки, фирменные приёмы, каталог компонентов, паттерны, тексты, правила design-lint |
| [`/styleguide`](http://localhost:5173/styleguide) | Живая витрина: все токены и компоненты во всех состояниях, обе темы (`make dev-frontend`) |
| [screenshots/](screenshots/) | Скриншоты витрины для команды и презентаций |
| [diagram-editor.md](diagram-editor.md) | Виджет редактора BPMN |
| [onboarding.md](onboarding.md) | Сценарий обучения, динамические якоря и доступность ввода |
| [RFC-0003](../rfc/0003-process-playback-and-timing.md) | Воспроизведение BPMN; предложенная модель бизнес-времени |
| [RFC-0001 §5.9](../rfc/0001-architecture.md) | Экраны продукта: три панели, вопросы, редактор |

## Где что лежит

| Путь | Что |
|---|---|
| `frontend/src/shared/styles/tokens.css` | Токены: палитра OKLCH, семантика светлой и тёмной темы, шрифты, радиусы, тени, движение |
| `frontend/src/shared/styles/base.css` | Глобальная база: фокус, выделение, скроллбары, сокращённое движение; утилиты `type-*`, `motion-*`, `pattern-*` |
| `frontend/src/shared/ui/` | Дизайн-система. Публичный API — `index.ts`, импорт только `@/shared/ui` |
| `frontend/src/shared/ui/icon/registry.ts` | Реестр иконок Tabler |
| `frontend/src/shared/lib/theme/` | Тема: `useTheme`, `ThemeProvider`, хранение в `localStorage` (`arkhitektor.theme`) |
| `frontend/src/shared/lib/format.ts` | Числа, даты, склонения по-русски |
| `frontend/src/shared/hooks/use-hotkey.ts` | Горячие клавиши (`mod` = ⌘ / Ctrl) |
| `frontend/src/app/providers.tsx` | Глобальные провайдеры: данные, тема, подсказки, уведомления |
| `frontend/src/features/theme-switch/` | Переключатель темы |
| `frontend/src/routes/styleguide.tsx`, `routes/-styleguide/` | Витрина (отдельный чанк, в стартовый бандл не входит) |
| `frontend/scripts/design-lint.mjs` | Правила дизайн-системы, тесты — `design-lint.test.mjs` |

## Быстрый старт для нового экрана

1. Откройте `/styleguide` и раздел 9 гайдбука — нужный компонент почти наверняка есть.
2. Собирайте из `@/shared/ui`, цвета — только семантические классы, текст — роли `type-*`.
3. После правок — `make check-fast`: design-lint подскажет, если что-то собрано в обход системы.
