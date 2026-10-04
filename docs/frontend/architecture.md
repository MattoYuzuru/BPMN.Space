# Архитектура фронтенда

Как устроены экраны «Архитектора BPMN»: слои, данные, ленивость, движение и проверки. Дизайн-система и тексты — в [styleguide.md](styleguide.md), редактор схемы — в [diagram-editor.md](diagram-editor.md), контракт API — `docs/api/openapi.json`.

## Экраны

| Маршрут | Что | Файлы |
|---|---|---|
| `/login` | Вход и регистрация (`?redirect=` — куда вернуть). Публичный | `routes/login.tsx`, `widgets/login-screen/`, `features/sign-in/` |
| `/` и `/projects` | Список проектов: поиск (`?q=`), область (`?scope=` — `own`, `shared`, `examples`), сетка карточек, бесконечная прокрутка, создание проекта | `routes/_app.index.tsx`, `routes/_app.projects.index.tsx`, `widgets/projects-grid/` |
| `/projects/$projectId` | Рабочее место: шапка, три панели (источники, схема, вопросы), ход прогона, листы вопроса, источника, отчёта и версий | `routes/_app.projects.$projectId.tsx`, `widgets/workspace/` и соседние виджеты |
| `/share/$token` | Публичная страница по ссылке «поделиться»: просмотр проекта только для чтения (гостю тоже), приглашение редактора, «ссылка недействительна / срок истёк». Лениво, вне `_app` | `routes/share.$token.tsx`, `widgets/share-page/`, `entities/share/` |
| `/studio/$projectId` | Старые ссылки перенаправляются в единственное рабочее место проекта | `routes/_app.studio.$projectId.tsx` |
| `/styleguide` | Живой стайлгайд | `routes/styleguide.tsx` |
| `/dev/diagram` | Витрина редактора BPMN для разработки; в навигации продукта ссылок на неё нет | `routes/dev.diagram.tsx` |
| любой другой | 404 | `widgets/route-states/` |

Состояние рабочего места живёт в адресе — ссылкой можно поделиться, «назад» работает: `?question=` (выбранный вопрос), `?version=` (просмотр старой версии, только чтение), `?source=&mark=` (открытый источник и цитата, к которой прокрутить).

У серверного проекта одно рабочее место — `/projects/$projectId`. Создание проекта (диалог в корне) ведёт туда же; отдельный редактор для локальных черновиков удалён, а старый `/studio/$projectId` оставлен только для перенаправления старых ссылок.

**Доступ.** Закрытые экраны — под pathless-маршрутом `routes/_app.tsx`: его `beforeLoad` (`requireSession` из `entities/session`) читает `/auth/session` и гостя при включённых аккаунтах отправляет на `/login?redirect=…`. Публичные маршруты (`/login`, `/styleguide`, `/dev/diagram`, `/share/$token`) лежат вне `_app`. `entities/session` — запрос сессии, вход, регистрация (сразу входит), выход, очистка кэша данных аккаунта, проверка адреса возврата. 401 посреди работы ловят `QueryCache`/`MutationCache` (`app/query-client.ts`) и ведут на вход (`app/session-expiry.ts`); 429 — спокойный тост. Права в проекте — `projectCapabilities(access)` в `entities/project`, компоненты получают `canEdit` / `canManage`. Подробности — styleguide §16.

Глобальные слои стоят в корне (`routes/__root.tsx`): палитра команд (Ctrl+K / ⌘K) и диалог создания проекта. Экран добавляет в палитру свои команды через `useRegisterCommands` (рабочее место — «Запустить анализ», «Построить схему», «Отчёт проверки»…).

## Слои

```
src/
  app/        провайдеры: QueryClient, тема, LazyMotion + MotionConfig, подсказки, уведомления
  routes/     тонкие маршруты TanStack Router: validateSearch, loader, pending/error, сборка экрана
  widgets/    крупные блоки экранов: projects-grid, workspace, project-header, share-page, sources-panel,
              questions-panel, diagram-panel, run-progress, version-sheets, diagram-editor, skeletons
  features/   действия пользователя: create-project, add-source, voice-record, answer-question,
              run-analysis, export-diagram, command-palette, theme-switch, sign-in, account-menu, share-project
  entities/   данные предметной области: project, source, question, run, version, example, session, share, onboarding —
              ключи запросов, queryOptions, мутации, модели и чистые функции
  shared/     api (клиент openapi-fetch и типы), ui (дизайн-система), lib, hooks, styles
```

Импорты идут сверху вниз: `routes → widgets → features → entities → shared`. Сущности не знают про экраны; общая логика (сортировка вопросов, редьюсер прогона, поиск цитат, дифф элементов схемы) — чистые функции в `entities/*/model.ts`, покрытые Vitest.

## Данные

**Клиент.** `shared/api/client.ts`: `api` — типизированный `openapi-fetch` по `schema.gen.ts`, `unwrap()` превращает ответ в данные или `ApiError` с `detail` бэкенда. Multipart (файлы, аудио) — `postForm()` на XMLHttpRequest ради хода загрузки.

**Ключи запросов** (иерархические — инвалидируются пачкой):

| Ключ | Данные | Свежесть |
|---|---|---|
| `['projects', 'list', { q, scope }]` | страницы списка (`useInfiniteQuery`, курсор); у каждой области («все», «мои», «общие», «примеры») свой кэш | 15 с, фокус окна |
| `['projects', 'detail', id]` | проект целиком: источники, вопросы, сводка, последняя версия без XML, активный прогон | 15 с, фокус окна, SSE |
| `['projects', 'detail', id, 'versions']` | версии проекта | вложен в проект: инвалидация проекта обновляет и его |
| `['versions', id]` | версия с XML | неизменна: `staleTime: Infinity` |
| `['projects', 'detail', id, 'share-links']`, `[…, 'members']` | ссылки доступа и участники (диалог «Поделиться», только владелец) | всегда перечитываются при открытии |
| `['shares', token]` | проект по ссылке (`SharedProject`: роль и `detail`); без повторов — 401, 404, 410 это состояния страницы | 60 с |
| `['shares', token, 'version', id]` | XML версии по ссылке; версия = `detail.latest_version` + XML | неизменна |
| `['share-access', projectId]` | есть ли у вошедшего доступ к проекту (чтобы не предлагать «принять» владельцу) | не кэшируется |
| `['examples']` | демо-примеры | `staleTime: Infinity`, грузятся при открытии диалога |

**Кнопок «Обновить» нет.** Данные обновляются сами:

- `refetchOnWindowFocus` — вернулись во вкладку, проект перечитан;
- SSE прогона (`features/run-analysis/use-run-tracker.ts`): событие `question` сразу кладёт вопрос в кэш проекта (карточки решаются вживую), `version` — новую версию в список, `done` — инвалидирует проект и список;
- опрос — только пока есть источники в статусе `processing` (`refetchInterval` в `projectQueryOptions`: 1,5 с, затем выключается сам).

**Loader'ы** вызывают `queryClient.ensureQueryData` — экран появляется уже с данными, а при наведении на ссылку (`defaultPreload: 'intent'`) всё начинает грузиться заранее. Loader рабочего места параллельно тянет проект, XML последней версии и чанк редактора (`preloadDiagramEditor()`).

**Оптимистичные обновления** — где действие почти всегда успешно и важна мгновенная реакция:

| Действие | Где | Откат |
|---|---|---|
| ответ, игнор, возврат вопроса | `entities/question/api.ts` (`useQuestionAction`) | снимок кэша проекта; toast с «Повторить» |
| переименование проекта | `entities/project/api.ts` (`useRenameProject`) | снимок проекта; списки перезапрашиваются |
| удаление проекта | `useDeleteProject` | снимки всех страниц списков |
| включить/выключить, править, удалить источник | `entities/source/api.ts` | снимок проекта |
| состояние тура и чек-листа | `entities/onboarding/api.ts` (`useOnboarding`, `useUpdateTour`, `useSetChecklistHidden`, `useReportOnboardingEvent`) | ключ включает id пользователя; ответ сервера кладётся в кэш; отметка клиента не уходит, если пункт уже выполнен |
| учебные материалы («Примеры») | `entities/source/api.ts` (`useSamples`, `useAddSampleSource`) | как у остальных источников: снимок проекта |
| сохранение правки схемы | `entities/version/api.ts` (`useSaveDiagram`) | не оптимистично: XML кладётся в кэш новой версии после ответа, редактор не перечитывает схему |

Сводка вопросов при оптимистичном переходе сдвигается функцией `shiftSummary`; точные числа приходят следующим запросом.

## Общий доступ и источник данных рабочего места

Рабочее место не знает, откуда пришёл проект. `WorkspaceView` (`widgets/workspace`) получает пропсами `project` (`ProjectDetail`), `versions` (`VersionSource`), `header` и флаги `readOnly` / `commands`, строит из них `WorkspaceApi` и раздаёт его панелям через контекст (`useWorkspace()`). Два потребителя:

- `Workspace` — проект аккаунта: `useQuery(projectQueryOptions)`, SSE прогона, команды палитры, `projectVersionSource` (запросы по id версии, список версий, скачивание `/versions/{id}/xml`).
- `SharedWorkspace` (`widgets/share-page`) — просмотр по ссылке: `project` берётся из `SharedProject.detail`, `readOnly`, команд нет, `shareVersionSource(token, detail)`.

`VersionSource` (`entities/version`) — единственный шов: `detail(versionId)` (версия с XML), `list(projectId)`, `xmlUrl(versionId)` и флаг `history`. Для ссылки доступна только последняя версия, поэтому `shareVersionSource` собирает `VersionDetail` из `detail.latest_version` (отчёт, трассировка, дифф уже в ответе) и XML с `/shares/{token}/versions/{id}/xml`, список — из одной версии, `history: false` прячет историю версий и просмотр старых. Панели, листы и скачивание читают версии только через `useWorkspace().versions`, поэтому в общий кэш проектов ничего подставного не кладётся: данные публичной страницы живут под своим корнем `['shares', token]`.

Страница `/share/$token` разбирает ответ сервера в `sharePageState` (чистая функция, `entities/share/model.ts`), роль и права посетителя решаются по ответам API, а не по клиентским догадкам. Выход из аккаунта на этой странице перезагружает её. Общая шапка публичных страниц — `PublicHeader` (`widgets/app-header`); `DownloadMenu` (`widgets/project-header`) общий у шапки проекта и шапки просмотра. Палитра команд и диалог создания проекта в корне на этой странице не монтируются.

Диалог «Поделиться» (`features/share-project`) монтирует содержимое только на время показа: адрес новой ссылки хранится в состоянии компонента и пропадает при закрытии. Токен не попадает в уведомления, заголовок вкладки и тексты ошибок.

## Прогон и SSE

1. `useStartRun` → `POST /projects/{id}/runs` → прогон кладётся в проект (`active_run`, статус) и в стор `useRunStore` — панель хода открывается сразу.
2. `useRunTracker` открывает `openRunStream` (`entities/run/stream.ts`): EventSource на `/api/v1/runs/{id}/events`. Обрыв в состоянии `CONNECTING` браузер переживает сам (с `Last-Event-ID`); если поток закрыт, переподключаемся с паузой 1, 2, 4, 8, 10 с; после 8 попыток — предупреждение и перезапрос проекта. На `done` поток закрывается.
3. События сворачивает чистый редьюсер `reduceRun` (`entities/run/model.ts`). Он идемпотентен: событие с номером не больше обработанного отбрасывается, поэтому история, которую сервер присылает при переподключении, ничего не ломает.
4. `RunProgress` (`widgets/run-progress`) рисует Stepper этапов с длительностями и линию тока, показывает прошедшее время и подсказку на долгих этапах модели, после завершения — итог «Решено N | Осталось N | Новых N»; через 6 с сворачивается сам. Шапка показывает линию тока по нижней кромке, пока прогон идёт.

## Бесконечная прокрутка

`useLoadMore` (`shared/hooks/use-load-more.ts`) ставит IntersectionObserver на карточку с индексом `sentinelIndex(loaded, columns)` — это ≈ 90 % загруженного, округлённое вниз до начала ряда сетки (число колонок меряет `useGridColumns`). Как только эта карточка показалась в окне, грузится следующая страница — пользователь не упирается в конец списка. Порог считается по числу элементов, а не по высоте страницы, поэтому не зависит от ширины окна. Пока грузится страница — по ряду скелетонов.

Виртуализацию (`@tanstack/react-virtual`) в списке проектов не включаем: карточек десятки, высота у них разная, а сетка адаптивная — виртуальная сетка добавила бы сложности без выигрыша. Порог, при котором стоит вернуться к вопросу, — сотни карточек.

## Ленивость и бюджет

- Маршруты режутся на чанки автоматически (`autoCodeSplitting`). `pendingComponent` маршрутов в чанк не уходит, поэтому заглушки экранов вынесены в `widgets/skeletons/screen-skeletons.tsx` и не импортируют виджеты — иначе экраны попали бы в стартовый бандл.
- bpmn-js с плагинами — отдельный чанк `LazyDiagramEditor` (≈ 460 КБ gzip), грузится в loader рабочего места и при наведении на проект.
- Палитра команд (cmdk), диалог создания проекта, экраны 404 и ошибки — `React.lazy` по первому требованию.
- Возможности motion (`domAnimation`) грузятся отдельным чанком через `LazyMotion`; экраны используют только лёгкие `m.*`.
- `make build` проверяет бюджет: стартовые JS и CSS ≤ 200 КБ gzip, без bpmn-js (`frontend/scripts/check-bundle.mjs`).

## Движение

Пресеты — `shared/lib/motion.ts` (те же `ease-soft` и длительности, что в CSS). Используем: появление карточек каскадом (≤ 0,3 с), уход решённого вопроса во вкладку «Решено» (карточка ≈ 2 с показывает доказательство, затем уезжает), всплытие панелей хода прогона и карточки элемента схемы. Раскладку не анимируем. `MotionConfig reducedMotion="user"` выключает движение при `prefers-reduced-motion`.

## Голос

`features/voice-record`: `useVoiceRecorder` — MediaRecorder (webm/ogg opus) и уровень сигнала из AnalyserNode (RMS формы волны, ≈ 16 значений в секунду); отказ в доступе, отсутствие микрофона и неподдерживаемый браузер — отдельные состояния с объяснением, без `alert`. `VoiceCapture` — запись → `POST /transcriptions` → правка расшифровки → «Добавить как источник» или «Отправить ответ».

## Ширина окна

Только десктоп, 1024–2560 px. Боковые панели рабочего места тянутся и сворачиваются в полосу 44 px (`collapsible`), раскладка запоминается (`useDefaultLayout`). Карточки и сетки подстраиваются под ширину своей панели (`@container`), шапка на узком окне прячет подписи («Команды», название продукта, плашку итогов — она остаётся в карточке хода прогона).

## Как добавить экран

1. Маршрут `src/routes/<путь>.tsx`: `validateSearch` для состояния в адресе, `loader` с `context.queryClient.ensureQueryData(...)`, `pendingComponent` из `widgets/skeletons`, `errorComponent: RouteErrorScreen`.
2. Данные — в `entities/<сущность>/api.ts`: ключ в иерархии, `queryOptions`, мутации с инвалидацией (и оптимистичным обновлением, если действие почти всегда успешно).
3. Действия пользователя — `features/<действие>/`, блоки экрана — `widgets/<блок>/`; UI только из `@/shared/ui`.
4. Команды экрана — `useRegisterCommands('<id>', group)`.
5. Тесты: логика — Vitest рядом с кодом; сценарий — `frontend/e2e/*.spec.ts`; кадр — в `e2e/screenshots.spec.ts`.
6. `make check-fast` после правок, `make check` перед пушем.

## Проверки

- `npm run --workspace frontend test` — Vitest: редьюсер и поток SSE (поддельный EventSource), оптимистичные обновления с откатом, порог прокрутки, цитаты в источниках, дифф элементов схемы, переходы вопросов, уровень сигнала, форматирование.
- `make e2e` — Playwright против Docker-стека. Против dev-сервера: `make dev-backend` с `MOCK_DELAY_SCALE=0.2`, vite на своём порту и `E2E_BASE_URL=http://localhost:<порт> npm run --workspace frontend e2e -- --project=e2e`. Микрофон поддельный (`--use-fake-device-for-media-stream`).
- `make screenshots` — 16 кадров в `reports/screenshots/` (1600×1000, 2×) на свежем mock-бэкенде с `MOCK_DELAY_SCALE=1`: кадр хода прогона снимается посреди анализа.
