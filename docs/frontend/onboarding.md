# Обучение: движок тура и подсказок

Как устроено обучение новичка: затемнение с «прожектором», карточка с печатью текста, машина шагов и подсказки-указатели. Здесь описан **движок** (`features/onboarding/tour`, `features/onboarding/hint`, компоненты в `shared/ui`). Сценарий из 11 шагов и приветствие добавляются отдельной задачей и дополнят этот документ; чек-лист «Начало работы» описан в конце. Визуальные правила — [styleguide.md](styleguide.md) (§5 слои Z, §9 «Обучение», §10 паттерн «Обучение»), живые примеры — раздел «Обучение» на `/styleguide`.

## Принцип

Обучение — надстройка. **Фичи не импортируют `features/onboarding`**: они ставят атрибуты `data-tour` и публикуют сигналы, а тур только слушает. Всё общее лежит в `shared`:

| Что | Где |
|---|---|
| Якоря `data-tour`, константы, `tourAnchor()`, `anchorSelector()`, защита слоёв | `shared/lib/tour-anchors.ts` |
| Шина сигналов приложения | `shared/lib/onboarding-signals.ts` |
| `Spotlight`, `CoachCard`, `Typewriter`, `Beacon` | `shared/ui` |
| `useTypewriter`, `useElementRect` | `shared/hooks` |

Движок грузится отдельным лениво подгружаемым чанком: `TourHost` подключает его, только когда тур активен; без тура нет ни одного `MutationObserver` или `ResizeObserver`, а публикация сигнала без подписчиков — пустая проверка.

## Якоря

Целевой элемент помечается `data-tour="…"`; значения — константы `TOUR_ANCHORS` (`projects.new`, `create.submit`, `sources.add`, `run.build`, `share.open` и др.):

```tsx
<Button {...tourAnchor(TOUR_ANCHORS.sourcesAdd)}>Добавить источник</Button>
```

Элемент должен принимать `data-*` (компоненты дизайн-системы отдают его на корневой DOM-узел; если нет — оберните в `span`). Якорь внутри контейнера: `{ name: 'question.answer', within: '[data-question-id="q1"]' }`; произвольный селектор: `{ selector: '…' }`.

## Сигналы

Фичи публикуют факты **после успеха на сервере**:

```ts
emitOnboardingSignal({ type: 'source.added', kind: 'text' })
```

| Сигнал | Данные |
|---|---|
| `project.created` | `id` |
| `source.added` | `kind` |
| `voice.permission-denied`, `voice.unavailable` | нет |
| `run.started` | `id` |
| `run.status` | `status`: `queued` / `running` |
| `run.finished` | `status`, `openQuestions`, `hasDiagram` |
| `question.answered`, `question.ignored` | `id` |
| `share.created` | нет |
| `dialog.opened` | `name` |

Подписка — `subscribeOnboardingSignals(listener)` (возвращает отписку).

## Шаг тура

Шаг — данные (`TourStep<Ctx>`, `features/onboarding/tour/types.ts`):

| Поле | Что |
|---|---|
| `key`, `chapter`, `title` | ключ шага (совпадает с бэкендом), ключ главы (подпись — в `chapters` у `TourHost`), заголовок карточки |
| `kind` | `story` рассказ («Назад»/«Далее»), `action` действие («Пропустить шаг»), `wait` ожидание, `finish` финал по центру |
| `pages` | 1–3 страницы: `{ text, title?, anchor?, side?, allowOutside? }`; страница перекрывает якорь шага |
| `anchor`, `side` | якорь (значение, `{name, within}`, `{selector}` или функция от контекста); нет — по центру |
| `route(ctx)` | экран шага `{ to, params?, search?, alt? }`: движок сам переходит туда, а если пользователь ушёл — ставит тур на паузу |
| `until(signal, ctx)` | сигнал, завершающий `action`/`wait` |
| `doneWhen(ctx)` | то же по состоянию приложения (проверяется после каждого обновления контекста) |
| `skipIf(ctx)` | шаг пропускается — при входе и пока идёт (ветвления); не должен давать `true`, пока данные грузятся |
| `optional` | якорь не найден за таймаут — шаг молча пропускается |
| `prepare(ctx)` | подготовить экран при входе (развернуть панель через публичный стор фичи); может вернуть функцию очистки |
| `allowOutside` | клики вне выреза разрешены |
| `actions` | кнопки справа вместо стандартных: `{ id, label, variant?, tone?, run(api) }`; `api` — `next`, `back`, `skipStep`, `goto(key)`, `finish(reason)` |
| `view(v)` | динамический вид: `{ title?, pages?, tone?, actions?, anchor?, side?, allowOutside? }`; `v` — `ctx`, `elapsedMs`, `seen` (сигналы шага), `page` |
| `ticks` | моменты (мс от входа), в которые пересчитать `view` (таймауты 60 и 150 с) |

Правила машины: «Назад» показывается только у рассказов (на первой странице — если предыдущий шаг тоже рассказ); «Далее» на последней странице идёт к следующему непропущенному шагу, после последнего тур завершается как `completed`; `goto(key)` нужен для ветвлений («Повторить», «Пропустить главу»); завершение — крестик или `Esc` и подтверждение внутри карточки (`dismissed`).

Ожидание якоря: `MutationObserver` плюс опрос раз в 250 мс до `anchorTimeoutMs` (по умолчанию 5 с). Пока ждём — затемнение держится, карточки нет. Не нашли: карточка по центру без выреза; у шага-действия ожидание сигнала продолжается.

## Подключение

```tsx
<TourHost
  enabled={onboarding.tour.status === 'active'}   // сервер говорит «тур идёт»: восстановить шаг
  steps={steps}
  context={ctx}                                    // id проекта, вопросы, прогон…
  persistence={persistence}
  chapters={{ sources: 'Источники', questions: 'Вопросы', diagram: 'Схема' }}
  onEnd={(reason) => …}                            // 'completed' | 'dismissed'
/>
```

`startTour(stepKey)` запускает тур с шага, `stopTour()` останавливает без записи на сервер.

**`TourPersistence`** — интерфейс хранения, движок не знает про API:

```ts
interface TourPersistence {
  load(): Promise<{ status: 'pending' | 'active' | 'completed' | 'dismissed'; step: string | null }>
  saveStep(step: string): Promise<unknown> | undefined   // вход в шаг
  setStatus(status: 'active' | 'completed' | 'dismissed'): Promise<unknown> | undefined
}
```

Вызовы идут в фоне, без ожидания ответа, с одним повтором через 1,5 с при ошибке. При монтировании (`restore`, по умолчанию включено) движок берёт `load()` и, если тур активен, продолжает с сохранённого шага (его повторно не пишет). Отдельной логики для нескольких вкладок нет: побеждает последнее изменение.

## Слои и модальные окна

Шаги, подсвечивающие элемент внутри `Dialog` или `Sheet`, ломают наивную схему: модальный слой делает `body` некликабельным, держит фокус и закрывается по клику снаружи и по `Esc`. Поэтому:

- затемнение тура не рисуется (у окна своё), остаётся кольцо у элемента;
- карточка рендерится внутрь узла окна (портал с `container`), то есть внутри `FocusScope`; её показ ждёт окончания анимации окна;
- `DialogContent`, `SheetContent`, `DropdownMenuContent` и `PopoverContent` игнорируют `onInteractOutside` и `onEscapeKeyDown`, если событие внутри `[data-tour-layer]` (`guardTourLayer`); для касаний слой запоминает, где началось нажатие;
- меню `DropdownMenu` тур не открывает и не контролирует; пока меню или список выбора открыты, затемнение и перехват кликов снимаются (меню лежит на `z-50` под затемнением `z-60`).

## Подсказка-указатель

`showHint({ anchor, text, prepare? })` из `features/onboarding/hint`: пульсирующее кольцо и поповер с «Понятно», без затемнения; одна подсказка за раз. `prepare` готовит экран; якорь не найден за 5 с — `toast` с тем же текстом. Хост — `<HintHost />` (грузит чанк, только когда есть подсказка).

## Как добавить шаг

1. Поставьте `data-tour` на целевой элемент (константа в `TOUR_ANCHORS`) и, если нужно, опубликуйте сигнал после успеха на сервере.
2. Опишите шаг в сценарии: `kind`, `anchor`, `pages` (до 160 символов, на «вы», без восклицаний), `until`/`doneWhen` для действий, `skipIf` для ветвлений.
3. Покажите его на `/styleguide` → «Обучение», если это новый вид шага.
4. Тесты — рядом с кодом (`machine.test.ts`, `tour-host.test.tsx`).

## Чек-лист «Начало работы»

12 пунктов в 4 группах; источник правды — бэкенд ([../backend/onboarding.md](../backend/onboarding.md)), на фронтенде — метаданные пунктов (`entities/onboarding/items.ts`) и показ. Паттерн и состояния — [styleguide.md](styleguide.md) §10, раздел «Начало работы» на `/styleguide`.

| Что | Где |
|---|---|
| Данные, мутации, `fetchItemTarget`, `useChecklistView` (прогресс для меню, плашки, панели) | `entities/onboarding` |
| Открыть панель из любого места: `useOnboardingUi().openChecklist()` | `entities/onboarding/ui.ts` (нейтральный стор: меню аккаунта, плашка, уведомление и тур не импортируют друг друга) |
| Пункт меню аккаунта | `features/account-menu` |
| Панель, переход к пункту, уведомления, слой в `_app` | `widgets/onboarding-checklist` |
| Плашка | `widgets/onboarding-pill` |

### Свежесть данных

Состояние перечитывается (`invalidateQueries(['onboarding'])`) после **любой** успешной мутации (`MutationCache.onSuccess` в `app/query-client.ts`, без фильтра: у мутаций нет общего ключа, а загрузка файла — тоже мутация, пусть и через XHR), после прогона (сигнал `run.finished` и конец прогона в `useRunTracker`). Кнопок «Обновить» нет.

### Клиентские пункты

`simulation_run` — при включении симуляции (`diagram-toolbar`), `diagram_exported` — когда файл отдан браузеру (`exportDiagram({ onSaved })`, оба меню скачивания). Отправляет `useReportOnboardingEvent`: если пункт уже отмечен в кэше — запрос не уходит, ответ не ждём.

### Переход к пункту

`useVisitItem().visit(item)`:

1. `GET /me/onboarding/items/{item}/target` → `{route, project_id?, question_id?, hint}`;
2. панель закрывается, переход на экран проектов или в рабочее место (`?question=<id>`, если сервер назвал вопрос);
3. `planItemVisit` (`target.ts`) выбирает якорь по `item` и `hint` (`TOUR_ANCHORS`; для вопросов — внутри `[data-question-id]`) и текст подсказки; `showHint` показывает указатель. Перед показом `prepare` раскрывает панель «Источники» или «Вопросы» и вызывает `selectQuestion(id, { focus: true })` — через `getWorkspaceControls()` (`widgets/workspace/model.ts`): рабочее место регистрирует управление при монтировании, поэтому подсказка работает снаружи его дерева.

Подсказка закрывается сама, когда пункт стал выполненным (`OnboardingWatcher`). Не нашли якорь за 5 с — тот же текст уведомлением (это делает `HintHost`).

### Уведомления

`OnboardingWatcher` (в `OnboardingLayer`, подключённом в `routes/_app.tsx`) — единственное место, где сравниваются ответы `GET /me/onboarding`. Первый ответ не объявляется; во время тура (и в тот же ответ, в котором он закончился) — тишина; один новый пункт — «Готово: …», несколько — «Готово: N шагов», последний — «Вы освоили Архитектор». Недавние пункты (5 с) запоминаются для анимации в панели.

### Как добавить пункт

1. Ключ приходит из контракта API (`ChecklistItem`); без записи в `META`/`ORDER` в `items.ts` проект не соберётся.
2. Якорь действия — в `DO_ANCHOR`, текст — в `DO_TEXT` (`widgets/onboarding-checklist/target.ts`); если действия может не быть на экране — раскрытие панели в `planItemVisit`.
3. Тест в `target.test.ts` проверит оба сопоставления для всех пунктов.
