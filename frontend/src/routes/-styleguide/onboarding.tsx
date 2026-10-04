import { type RefObject, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { HintHost, showHint } from '@/features/onboarding/hint'
import { startTour, TourHost, useTourStore } from '@/features/onboarding/tour'
import { useTypewriter } from '@/shared/hooks/use-typewriter'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Beacon,
  Button,
  CoachCard,
  Dialog,
  DialogClose,
  DialogContent,
  Field,
  Input,
  type Rect,
  SegmentedControl,
  Spotlight,
  Typewriter,
} from '@/shared/ui'
import { createDemoPersistence, DEMO_ANCHORS, DEMO_DIALOG, demoSteps } from './demo-tour'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

/** Прямоугольник элемента внутри контейнера (витрине вырез и кольцо рисуются в рамке образца). */
function useRelativeRect(container: RefObject<HTMLElement | null>, target: HTMLElement | null) {
  const [rect, setRect] = useState<Rect | null>(null)
  useEffect(() => {
    const host = container.current
    if (!host || !target) {
      setRect(null)
      return
    }
    const measure = () => {
      const a = host.getBoundingClientRect()
      const b = target.getBoundingClientRect()
      setRect({ x: b.x - a.x, y: b.y - a.y, width: b.width, height: b.height })
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(host)
    observer.observe(target)
    return () => observer.disconnect()
  }, [container, target])
  return rect
}

/** Разделитель подписи карточки: символ задан кодом, чтобы design-lint не принял его за иконку. */
const SEP = ' \u00b7 '

const SPOT_OPTIONS = [
  { value: 'sources', label: 'Источники' },
  { value: 'diagram', label: 'Схема' },
  { value: 'questions', label: 'Вопросы' },
] as const

type SpotValue = (typeof SPOT_OPTIONS)[number]['value']

function SpotlightDemo() {
  const [selected, setSelected] = useState<SpotValue>('sources')
  const [attention, setAttention] = useState(0)
  const stage = useRef<HTMLDivElement>(null)
  const [targets, setTargets] = useState<Partial<Record<SpotValue, HTMLElement | null>>>({})
  const rect = useRelativeRect(stage, targets[selected] ?? null)
  // Стабильные ref-колбэки: новые на каждый рендер дали бы цикл «отцепить и прицепить».
  const bind = useMemo(
    () =>
      Object.fromEntries(
        SPOT_OPTIONS.map(({ value }) => [
          value,
          (node: HTMLElement | null) =>
            setTargets((prev) => (prev[value] === node ? prev : { ...prev, [value]: node })),
        ]),
      ) as Record<SpotValue, (node: HTMLElement | null) => void>,
    [],
  )
  return (
    <div className="flex flex-col gap-4">
      <SegmentedControl
        aria-label="Подсвеченный элемент"
        size="sm"
        options={[...SPOT_OPTIONS]}
        value={selected}
        onValueChange={setSelected}
      />
      <div
        ref={stage}
        className="relative flex h-44 items-center justify-around gap-3 overflow-hidden rounded-lg border border-border bg-bg-subtle px-6"
      >
        <Button ref={bind.sources} leadingIcon="file-upload">
          Добавить источник
        </Button>
        <Button ref={bind.diagram} leadingIcon="diagram">
          Построить схему
        </Button>
        <Button ref={bind.questions} leadingIcon="message-question">
          Вопросы
        </Button>
        <Spotlight
          position="absolute"
          target={rect}
          transitionKey={selected}
          onBlockedClick={() => setAttention((n) => n + 1)}
        />
      </div>
      <CoachCard
        placement="inline"
        eyebrow={`Источники${SEP}Шаг 2 из 11`}
        title="Клик по затемнению"
        text="Нажмите на затемнённую область рамки выше: рамка этой карточки коротко подсветится акцентом."
        pageKey="spotlight-demo"
        attention={attention}
        actions={[{ id: 'a', label: 'Пропустить шаг', variant: 'ghost', onClick: () => {} }]}
        className="w-full max-w-80"
      />
    </div>
  )
}

const CARD_TEXT = 'Модель прочитает источники, найдёт неясности и соберёт схему BPMN.'

function CoachCardStates() {
  const noop = () => {}
  return (
    <div className="grid gap-6 @3xl:grid-cols-2">
      <div>
        <Caption>Рассказ: три страницы, «Назад» и «Далее»</Caption>
        <CoachCard
          placement="inline"
          eyebrow={`Схема${SEP}Шаг 9 из 11`}
          title="Работа со схемой"
          text="Это обычный редактор BPMN: двигайте элементы, правки сохраняются сами."
          pageKey="story"
          pageCount={3}
          pageIndex={1}
          onBack={noop}
          onNext={noop}
          onRequestEnd={noop}
          actions={[{ id: 'next', label: 'Далее', variant: 'primary', onClick: noop }]}
        />
      </div>
      <div>
        <Caption>Действие: «Пропустить шаг», основная кнопка не нужна</Caption>
        <CoachCard
          placement="inline"
          eyebrow={`Источники${SEP}Шаг 1 из 11`}
          title="Первый проект"
          text="Каждая схема живёт в своём проекте. Создайте первый — название можно поменять."
          pageKey="action"
          onRequestEnd={noop}
          actions={[{ id: 'skip', label: 'Пропустить шаг', variant: 'ghost', onClick: noop }]}
        />
      </div>
      <div>
        <Caption>Ждём: спиннер у счётчика, например пока разбирается документ</Caption>
        <CoachCard
          placement="inline"
          eyebrow={`Вопросы${SEP}Шаг 5 из 11`}
          title="Построить схему"
          text="Ждём, пока документ разберётся…"
          pageKey="waiting"
          tone="waiting"
          onRequestEnd={noop}
        />
      </div>
      <div>
        <Caption>Ошибка: заголовок тона Сурик, свои кнопки шага</Caption>
        <CoachCard
          placement="inline"
          eyebrow={`Вопросы${SEP}Шаг 6 из 11`}
          title="Модель не ответила"
          text="Попробуем ещё раз? Прогон можно повторить или пропустить главу."
          pageKey="error"
          tone="error"
          onRequestEnd={noop}
          actions={[
            { id: 'skip', label: 'Пропустить главу', variant: 'ghost', onClick: noop },
            { id: 'retry', label: 'Повторить', variant: 'primary', onClick: noop },
          ]}
        />
      </div>
      <div>
        <Caption>Завершение: подтверждение внутри самой карточки</Caption>
        <CoachCard
          placement="inline"
          eyebrow={`Источники${SEP}Шаг 3 из 11`}
          title="Текстовый источник"
          text={CARD_TEXT}
          pageKey="confirm"
          confirming
          onRequestEnd={noop}
          onConfirmEnd={noop}
          onCancelEnd={noop}
        />
      </div>
    </div>
  )
}

const SUGGESTION =
  'Заявитель подаёт заявку на техприсоединение, сетевая организация проверяет документы и выдаёт технические условия.'

/** Печать в поле ввода: общий хук useTypewriter, ~120 символов в секунду. */
function TypeIntoInput() {
  const [value, setValue] = useState('')
  const [typing, setTyping] = useState(false)
  const typed = useTypewriter({
    text: SUGGESTION,
    cps: 120,
    punctuationPause: false,
    active: typing,
    onComplete: () => {
      setValue(SUGGESTION)
      setTyping(false)
    },
  })
  return (
    <div className="flex flex-col gap-3">
      <Field
        label="Описание процесса"
        hint="Любой ввод во время печати допечатывает текст и отдаёт поле вам."
      >
        <Input
          value={typing ? typed.text : value}
          placeholder="Опишите процесс своими словами"
          onChange={(event) => {
            if (typing) {
              typed.finish()
              setTyping(false)
            }
            setValue(event.target.value)
          }}
        />
      </Field>
      <div className="flex gap-2">
        <Button
          variant="primary"
          size="sm"
          disabled={typing}
          onClick={() => {
            setValue('')
            setTyping(true)
          }}
        >
          Вставить подсказку
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setTyping(false)
            setValue('')
          }}
        >
          Очистить
        </Button>
      </div>
    </div>
  )
}

function TypewriterDemo() {
  const [run, setRun] = useState(0)
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Caption>Текст карточки: ~45 символов в секунду, паузы на знаках препинания</Caption>
        <div className="min-h-16 rounded-lg border border-border bg-bg-subtle p-4 type-ui text-fg-muted">
          <Typewriter
            key={run}
            text="Опишите процесс своими словами — или примите подсказку. Клик или любая клавиша допечатают текст сразу."
          />
        </div>
        <div>
          <Button size="sm" leadingIcon="history" onClick={() => setRun((n) => n + 1)}>
            Напечатать заново
          </Button>
        </div>
      </div>
      <div>
        <Caption>Печать в поле ввода: тот же хук, ~120 символов в секунду</Caption>
        <TypeIntoInput />
      </div>
    </div>
  )
}

function BeaconDemo() {
  const [run, setRun] = useState(0)
  const stage = useRef<HTMLDivElement>(null)
  const [button, setButton] = useState<HTMLElement | null>(null)
  const rect = useRelativeRect(stage, button)
  return (
    <div className="flex flex-col gap-4">
      <Caption>Кольцо «Ток»: три импульса по 1,6 с и статичное кольцо</Caption>
      <div
        ref={stage}
        className="relative flex h-28 items-center justify-center rounded-lg border border-border bg-bg-subtle"
      >
        <Button ref={setButton} leadingIcon="share">
          Поделиться
        </Button>
        <Beacon key={run} position="absolute" target={rect} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" leadingIcon="history" onClick={() => setRun((n) => n + 1)}>
          Повторить пульс
        </Button>
        <Button
          size="sm"
          variant="primary"
          leadingIcon="info"
          {...tourAnchor('styleguide.demo.hint-trigger')}
          onClick={() =>
            showHint({
              anchor: 'styleguide.demo.hint-target',
              text: 'Здесь создаётся ссылка для коллег. Подсказка исчезнет, как только вы нажмёте на элемент.',
            })
          }
        >
          Показать подсказку
        </Button>
        <Button variant="secondary" size="sm" {...tourAnchor('styleguide.demo.hint-target')}>
          Элемент для подсказки
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() =>
            showHint({ anchor: 'styleguide.demo.nowhere', text: 'Сначала постройте схему.' })
          }
        >
          Якоря нет (уведомление через 5 с)
        </Button>
      </div>
      {createPortal(<HintHost />, document.body)}
    </div>
  )
}

function DemoTour() {
  const [log, setLog] = useState<string[]>([])
  const [dialogOpen, setDialogOpen] = useState(false)
  const running = useTourStore((state) => state.status === 'active')
  const persistence = useMemo(
    () => createDemoPersistence((line) => setLog((prev) => [line, ...prev].slice(0, 6))),
    [],
  )
  return (
    <div className="flex flex-col gap-4">
      <p className="type-ui text-fg-muted">
        Четыре шага по элементам ниже: рассказ, действие, элемент в окне и якорь, которого нет. Тур
        сохраняет шаг через интерфейс TourPersistence; здесь вызовы только показываются.
      </p>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-bg-subtle p-4">
        <span {...tourAnchor(DEMO_ANCHORS.story)}>
          <Badge tone="accent" variant="outline">
            Элемент рассказа
          </Badge>
        </span>
        <Button
          variant="secondary"
          leadingIcon="layout-sidebar"
          {...tourAnchor(DEMO_ANCHORS.action)}
          onClick={() => {
            setDialogOpen(true)
            emitOnboardingSignal({ type: 'dialog.opened', name: DEMO_DIALOG })
          }}
        >
          Открыть окно
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          leadingIcon="player-play"
          disabled={running}
          onClick={() => {
            setLog([])
            startTour('story')
          }}
        >
          Запустить демо-тур
        </Button>
        <span className="type-caption text-fg-subtle">Esc или крестик в карточке — завершить</span>
      </div>
      {log.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-lg border border-border bg-bg-subtle p-3 type-code text-fg-muted">
          {log.map((line, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: журнал вызовов, строки могут повторяться
            <li key={`${index}-${line}`}>{line}</li>
          ))}
        </ul>
      )}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent
          title="Окно демо-тура"
          description="Якорь внутри окна: карточка тура лежит внутри него и не закрывает его."
          footer={
            <DialogClose asChild>
              <Button variant="primary" {...tourAnchor(DEMO_ANCHORS.dialog)}>
                Понятно
              </Button>
            </DialogClose>
          }
        >
          <p className="type-ui text-fg-muted">
            Окно закрывается кнопкой, крестиком или Esc, когда фокус не в карточке тура.
          </p>
        </DialogContent>
      </Dialog>
      {/* Слои обучения — у корня документа: образец с isolate запирает z-индексы внутри себя. */}
      {createPortal(
        <TourHost
          steps={demoSteps}
          context={null}
          persistence={persistence}
          chapters={{ demo: 'Демо' }}
          anchorTimeoutMs={1500}
          restore={false}
        />,
        document.body,
      )}
    </div>
  )
}

export function OnboardingSection() {
  return (
    <Section
      id="onboarding"
      eyebrow="20 Обучение"
      title="Обучение"
      lead="Тур ведёт новичка по главному сценарию: затемнение с прожектором на одном элементе и рядом карточка с текстом, который печатается. Тур не меняет продукт: после него всё выглядит как раньше."
    >
      <SpecimenGrid>
        <Specimen
          title="Spotlight"
          note="вырез переезжает за 320 мс, клики вне выреза закрыты"
          canvas
        >
          <SpotlightDemo />
        </Specimen>
        <Specimen
          title="Typewriter и useTypewriter"
          note="клик допечатывает, reduced motion — сразу"
        >
          <TypewriterDemo />
        </Specimen>
      </SpecimenGrid>
      <Specimen
        title="CoachCard"
        note="состояния: рассказ, действие, ждём, ошибка, завершение"
        canvas
      >
        <CoachCardStates />
      </Specimen>
      <SpecimenGrid>
        <Specimen title="Beacon и подсказка-указатель" note="без затемнения, одна подсказка за раз">
          <BeaconDemo />
        </Specimen>
        <Specimen title="Демо-тур" note="4 шага по элементам стайлгайда">
          <DemoTour />
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
