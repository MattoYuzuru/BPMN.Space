import { useEffect, useMemo, useRef, useState } from 'react'
import {
  DISPLAY_CHUNK_CHARS,
  derivationCost,
  derivationLabel,
  findQuoteRanges,
  isAgentSource,
  isDerived,
  limitParts,
  type QuoteMark,
  type QuoteRange,
  quoteReferences,
  type Source,
  sourceKindOf,
  sourceMeta,
  sourceTrustInfo,
  splitByRanges,
  splitTimecodes,
  unreadablePagesText,
  useUpdateSource,
} from '@/entities/source'
import { cn } from '@/shared/lib/cn'
import { formatCount, formatDate, formatMoney } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  Field,
  Icon,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Sheet,
  SheetContent,
  Switch,
  Textarea,
  Tooltip,
} from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

const MARK_CLASS: Record<QuoteRange['kind'], string> = {
  about:
    'bg-amber-subtle text-fg decoration-amber/70 underline decoration-dashed underline-offset-4',
  evidence: 'bg-success-subtle text-fg decoration-success/70 underline underline-offset-4',
  trace:
    'bg-transparent text-fg decoration-accent/50 underline decoration-dotted underline-offset-4',
}

export interface SourceSheetProps {
  sourceId?: string
  /** Цитата, к которой нужно прокрутить и подсветить. */
  mark?: string
  onClose: () => void
}

/** Просмотр и правка источника с подсветкой цитат, на которые ссылаются вопросы и схема. */
export function SourceSheet({ sourceId, mark, onClose }: SourceSheetProps) {
  const { project } = useWorkspace()
  const source = project.sources.find((item) => item.id === sourceId)
  return (
    <Sheet open={Boolean(source)} onOpenChange={(open) => !open && onClose()}>
      {source && <SourceDetail key={source.id} source={source} mark={mark} onClose={onClose} />}
    </Sheet>
  )
}

function SourceDetail({
  source,
  mark,
  onClose,
}: {
  source: Source
  mark?: string
  onClose: () => void
}) {
  const { project, canEdit, selectQuestion, focusElements, openSource } = useWorkspace()
  const openQuestion = useWorkspaceUi((state) => state.openQuestionSheet)
  const update = useUpdateSource(project.id)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(source.title)
  const [content, setContent] = useState(source.content)
  const [referenceStart, setReferenceStart] = useState<number | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const kind = sourceKindOf(source)
  const derived = isDerived(source)
  const producer = derivationLabel(source)
  const trust = sourceTrustInfo(source.trust)
  const agent = isAgentSource(source)
  const cost = derivationCost(source)
  const unreadable = unreadablePagesText(source.unreadable_pages)
  // Запись без своего текста: её содержимое — в производных узлах (расшифровка), RFC-0006.
  const derivedNodes = project.sources.filter((item) => item.parent_id === source.id)
  const container = derivedNodes.length > 0 && !source.content
  const timed = source.derivation?.capability === 'speech_to_text'
  const editable =
    canEdit &&
    source.kind !== 'answer' &&
    !container &&
    (source.status === 'ready' || (derived && source.status === 'failed'))

  const marks = useMemo<QuoteMark[]>(() => {
    const list: QuoteMark[] = []
    for (const question of project.questions) {
      if (question.about?.source_id === source.id)
        list.push({ quote: question.about.quote, kind: 'about', ref: question.id })
      if (question.evidence?.source_id === source.id)
        list.push({ quote: question.evidence.quote, kind: 'evidence', ref: question.id })
    }
    for (const [elementId, quote] of Object.entries(project.latest_version?.trace ?? {})) {
      if (quote.source_id === source.id)
        list.push({ quote: quote.quote, kind: 'trace', ref: elementId })
    }
    return list
  }, [project.questions, project.latest_version, source.id])

  const target = useMemo(() => {
    if (!mark) return undefined
    const [hit] = findQuoteRanges(source.content, [{ quote: mark, kind: 'about', ref: 'target' }])
    return hit
  }, [mark, source.content])

  // Выбранная цитата важнее перекрывающей её подсветки: показываем весь фрагмент из ссылки.
  const ranges = useMemo(() => {
    const found = findQuoteRanges(source.content, marks)
    if (!target) return found
    const [linked] = findQuoteRanges(
      source.content,
      marks.filter((item) => item.quote === mark),
    )
    return [
      ...found.filter((range) => range.end <= target.start || range.start >= target.end),
      linked ?? { ...target, ref: '' },
    ].sort((left, right) => left.start - right.start)
  }, [source.content, marks, mark, target])
  const parts = useMemo(() => splitByRanges(source.content, ranges), [source.content, ranges])
  // Длинный документ показываем порциями: в DOM не выводим сразу сотни тысяч знаков.
  // Текст источника и поиск цитат не меняются; порция расширяется до цитаты, к которой пришли.
  const [shown, setShown] = useState(DISPLAY_CHUNK_CHARS)
  const visibleLimit = Math.max(shown, target ? target.end + 2_000 : 0)
  const visibleParts = useMemo(() => limitParts(parts, visibleLimit), [parts, visibleLimit])
  const hiddenChars = Math.max(source.content.length - visibleLimit, 0)
  const counts = { about: 0, evidence: 0, trace: 0 }
  for (const range of ranges) counts[range.kind] += 1

  // Открыли по цитате — прокручиваем к ней, когда панель уже выехала.
  useEffect(() => {
    if (!target) return
    const timer = setTimeout(() => {
      bodyRef.current?.querySelector('[data-target="true"]')?.scrollIntoView({
        block: 'center',
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
          ? 'instant'
          : 'smooth',
      })
    }, 260)
    return () => clearTimeout(timer)
  }, [target])

  const labelFor = (range: QuoteRange) => {
    if (range.kind === 'trace') return 'Элемент схемы'
    const question = project.questions.find((item) => item.id === range.ref)
    return question ? `${question.code}: ${question.text}` : 'Цитата'
  }

  const references = useMemo(
    () =>
      new Map(ranges.map((range) => [range.start, quoteReferences(source.content, range, marks)])),
    [ranges, source.content, marks],
  )

  const navigateTo = (ref: QuoteMark) => {
    onClose()
    if (ref.kind === 'trace') {
      focusElements([ref.ref])
    } else {
      selectQuestion(ref.ref, { focus: true })
      openQuestion(ref.ref)
    }
  }

  const save = () => {
    update.mutate(
      { id: source.id, title: title.trim() || source.title, content },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <SheetContent
      size="lg"
      title={source.title}
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="flex items-center gap-1.5">
            <Icon name={kind.icon} size={14} />
            {kind.label}
          </span>
          {derived && (
            <Badge tone="accent" icon="sparkles">
              ИИ
            </Badge>
          )}
          {agent && (
            <Badge tone="accent" icon="user">
              Агент
            </Badge>
          )}
          <Tooltip content={trust.description}>
            <span {...tourAnchor(TOUR_ANCHORS.sourceTrust)}>
              <Badge variant="outline" tone={trust.tone}>
                {trust.label}
              </Badge>
            </span>
          </Tooltip>
          {producer && <span>{producer}</span>}
          {cost !== null && <span>{formatMoney(cost)}</span>}
          {source.edited_by_human && (
            <Badge tone="neutral" icon="human-edit">
              Изменено человеком
            </Badge>
          )}
          <span data-numeric>{sourceMeta(source)}</span>
          <span>{formatDate(new Date(source.created_at))}</span>
        </span>
      }
      footer={
        editing ? (
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setEditing(false)
                setTitle(source.title)
                setContent(source.content)
              }}
            >
              Отмена
            </Button>
            <Button variant="primary" leadingIcon="check" loading={update.isPending} onClick={save}>
              Сохранить
            </Button>
          </>
        ) : (
          <>
            <Switch
              label="Участвует в анализе"
              checked={source.active}
              disabled={!canEdit}
              onCheckedChange={(active) => update.mutate({ id: source.id, active })}
            />
            <span className="flex-1" />
            {editable && (
              <Button
                leadingIcon="pencil"
                onClick={() => {
                  setTitle(source.title)
                  setContent(source.content)
                  setEditing(true)
                }}
              >
                Править текст
              </Button>
            )}
          </>
        )
      }
    >
      {editing ? (
        <div className="flex flex-col gap-4 animate-fade-in">
          <Field label="Название">
            <Input value={title} onChange={(event) => setTitle(event.target.value)} />
          </Field>
          <Field
            label="Текст"
            hint={
              derived
                ? 'Правка заменит текст, полученный ИИ, и узел будет отмечен «Изменено человеком»'
                : undefined
            }
          >
            <Textarea
              autoFocus
              value={content}
              minRows={14}
              maxRows={30}
              onChange={(event) => setContent(event.target.value)}
            />
          </Field>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {mark && !target && (
            <p
              role="status"
              className="rounded-md bg-amber-subtle px-3 py-2.5 type-ui text-amber-fg"
            >
              Цитата не найдена в текущем тексте. Возможно, источник был изменён. Исходная цитата: «
              {mark}»
            </p>
          )}
          {ranges.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {counts.about > 0 && (
                <Badge tone="amber" variant="outline" icon="message-question">
                  Повод для вопроса {counts.about}
                </Badge>
              )}
              {counts.evidence > 0 && (
                <Badge tone="success" variant="outline" icon="circle-check">
                  Доказательство {counts.evidence}
                </Badge>
              )}
              {counts.trace > 0 && (
                <Badge tone="accent" variant="outline" icon="diagram">
                  На схеме {counts.trace}
                </Badge>
              )}
            </div>
          )}
          {source.status === 'ready' && source.warning && (
            <div
              role="status"
              className="flex items-start gap-2 rounded-md bg-amber-subtle px-3 py-2.5 type-ui text-amber-fg"
            >
              <Icon name="alert-circle" size={16} className="mt-0.5" />
              {source.warning}
            </div>
          )}
          {unreadable && (
            <div
              role="status"
              className="flex items-start gap-2 rounded-md bg-amber-subtle px-3 py-2.5 type-ui text-amber-fg"
            >
              <Icon name="alert-triangle" size={16} className="mt-0.5" />
              {unreadable}
            </div>
          )}
          {source.status === 'failed' && (
            <div className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2.5 type-ui text-danger-fg">
              <Icon name="alert-circle" size={16} className="mt-0.5" />
              {source.error ?? 'Документ не удалось разобрать'}
            </div>
          )}
          {container && (
            <MediaContainer source={source} derived={derivedNodes} onOpen={openSource} />
          )}
          <div
            ref={bodyRef}
            className="max-w-2xl whitespace-pre-wrap type-body text-fg-muted"
            data-testid="source-content"
          >
            {visibleParts.map((part) =>
              part.range ? (
                <Popover
                  key={part.start}
                  open={referenceStart === part.start}
                  onOpenChange={(open) => setReferenceStart(open ? part.start : null)}
                >
                  <PopoverTrigger asChild>
                    <a
                      href={`?source=${source.id}`}
                      onClick={(event) => {
                        event.preventDefault()
                        setReferenceStart((current) => (current === part.start ? null : part.start))
                      }}
                      aria-label={`Связи фрагмента: ${labelFor(part.range)}`}
                      className="cursor-pointer rounded-xs outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
                    >
                      <mark
                        data-target={
                          target && part.range.start <= target.start && part.range.end >= target.end
                            ? 'true'
                            : undefined
                        }
                        className={cn(
                          'rounded-xs px-0.5 transition-[background-color,box-shadow] duration-slow ease-soft',
                          MARK_CLASS[part.range.kind],
                          'data-[target=true]:shadow-glow data-[target=true]:ring-1 data-[target=true]:ring-accent/40',
                        )}
                      >
                        {part.text}
                      </mark>
                    </a>
                  </PopoverTrigger>
                  <PopoverContent
                    aria-label="Связи фрагмента"
                    align="start"
                    className="flex flex-col gap-2"
                  >
                    <p className="type-label text-fg-muted">Связано с фрагментом</p>
                    {(references.get(part.start) ?? []).map((ref) => {
                      const question =
                        ref.kind === 'trace'
                          ? undefined
                          : project.questions.find((item) => item.id === ref.ref)
                      return (
                        <Button
                          key={`${ref.kind}:${ref.ref}`}
                          variant="ghost"
                          leadingIcon={ref.kind === 'trace' ? 'locate' : 'message-question'}
                          className="h-auto justify-start whitespace-normal py-2 text-left"
                          onClick={() => navigateTo(ref)}
                        >
                          {question
                            ? `${question.code}: ${question.text}`
                            : `Показать элемент ${ref.ref}`}
                        </Button>
                      )
                    })}
                    {(references.get(part.start)?.length ?? 0) === 0 && (
                      <p className="type-ui text-fg-subtle">
                        У фрагмента нет связей в текущей версии.
                      </p>
                    )}
                  </PopoverContent>
                </Popover>
              ) : timed ? (
                <TimedText key={part.start} text={part.text} />
              ) : (
                <span key={part.start}>{part.text}</span>
              ),
            )}
          </div>
          {hiddenChars > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={() => setShown((value) => value + DISPLAY_CHUNK_CHARS)}>
                Показать ещё
              </Button>
              <span className="type-ui text-fg-subtle" data-numeric>
                Показано {formatCount(visibleLimit, ['знак', 'знака', 'знаков'])} из{' '}
                {source.content.length}. Анализ использует весь текст.
              </span>
            </div>
          )}
        </div>
      )}
    </SheetContent>
  )
}

/** Текст расшифровки: таймкоды `[мм:сс]` выделены моноширинным приглушённым шрифтом. */
function TimedText({ text }: { text: string }) {
  return (
    <span>
      {splitTimecodes(text).map((piece, index) =>
        index % 2 === 1 ? (
          // Позиция стабильна: текст делится один раз на рендер, порядок кусков не меняется.
          // biome-ignore lint/suspicious/noArrayIndexKey: куски строки без собственных id
          <span key={index} data-timecode className="font-mono text-fg-subtle">
            {piece}
          </span>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: куски строки без собственных id
          <span key={index}>{piece}</span>
        ),
      )}
    </span>
  )
}

/**
 * Исходная запись: своего текста нет, содержимое — в производных узлах. Здесь же позже
 * появится плеер с перемоткой на таймкод цитаты (RFC-0006, шаг 5).
 */
function MediaContainer({
  source,
  derived,
  onOpen,
}: {
  source: Source
  derived: Source[]
  onOpen: (sourceId: string) => void
}) {
  return (
    <div
      className="flex flex-col gap-3"
      data-testid="media-container"
      {...tourAnchor(TOUR_ANCHORS.sourcePlayer)}
    >
      {source.media && (
        <div className="flex flex-wrap gap-1.5">
          {source.media.has_audio !== null && source.media.has_audio !== undefined && (
            <Badge
              tone={source.media.has_audio ? 'success' : 'amber'}
              variant="outline"
              icon="wave-sine"
            >
              {source.media.has_audio ? 'Есть звук' : 'Нет звука'}
            </Badge>
          )}
          {source.media.has_video && (
            <Badge tone="neutral" variant="outline" icon="video">
              Есть видео
            </Badge>
          )}
        </div>
      )}
      <p className="type-ui text-fg-muted">
        Модель читает не сам файл, а полученные из него материалы:
      </p>
      <div className="flex flex-col gap-1">
        {derived.map((item) => {
          const kind = sourceKindOf(item)
          return (
            <Button
              key={item.id}
              variant="ghost"
              leadingIcon={kind.icon}
              className="justify-start"
              onClick={() => onOpen(item.id)}
            >
              {item.title}
            </Button>
          )
        })}
      </div>
    </div>
  )
}
