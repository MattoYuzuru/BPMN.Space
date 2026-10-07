import { useEffect, useMemo, useRef, useState } from 'react'
import {
  findQuoteRanges,
  type QuoteMark,
  type QuoteRange,
  quoteReferences,
  SOURCE_KIND,
  type Source,
  sourceMeta,
  splitByRanges,
  useUpdateSource,
} from '@/entities/source'
import { cn } from '@/shared/lib/cn'
import { formatDate } from '@/shared/lib/format'
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
  const { project, canEdit, selectQuestion, focusElements } = useWorkspace()
  const openQuestion = useWorkspaceUi((state) => state.openQuestionSheet)
  const update = useUpdateSource(project.id)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(source.title)
  const [content, setContent] = useState(source.content)
  const [referenceStart, setReferenceStart] = useState<number | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const kind = SOURCE_KIND[source.kind]

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
            {canEdit && source.kind !== 'answer' && source.status === 'ready' && (
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
          <Field label="Текст">
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
          {source.status === 'failed' && (
            <div className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2.5 type-ui text-danger-fg">
              <Icon name="alert-circle" size={16} className="mt-0.5" />
              {source.error ?? 'Документ не удалось разобрать'}
            </div>
          )}
          <div
            ref={bodyRef}
            className="max-w-2xl whitespace-pre-wrap type-body text-fg-muted"
            data-testid="source-content"
          >
            {parts.map((part) =>
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
                      data-target={
                        target && part.range.start <= target.start && part.range.end >= target.end
                          ? 'true'
                          : undefined
                      }
                      className={cn(
                        'cursor-pointer rounded-xs px-0.5 outline-none transition-[background-color,box-shadow] duration-slow ease-soft focus-visible:ring-2 focus-visible:ring-focus-ring',
                        MARK_CLASS[part.range.kind],
                        'data-[target=true]:shadow-glow data-[target=true]:ring-1 data-[target=true]:ring-accent/40',
                      )}
                    >
                      {part.text}
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
              ) : (
                <span key={part.start}>{part.text}</span>
              ),
            )}
          </div>
        </div>
      )}
    </SheetContent>
  )
}
