import { useEffect, useMemo, useRef, useState } from 'react'
import {
  findQuoteRanges,
  type QuoteMark,
  type QuoteRange,
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
  Sheet,
  SheetContent,
  Switch,
  Textarea,
  Tooltip,
} from '@/shared/ui'
import { useWorkspace } from '@/widgets/workspace/model'

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
      {source && <SourceDetail key={source.id} source={source} mark={mark} />}
    </Sheet>
  )
}

function SourceDetail({ source, mark }: { source: Source; mark?: string }) {
  const { project } = useWorkspace()
  const update = useUpdateSource(project.id)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(source.title)
  const [content, setContent] = useState(source.content)
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

  // Цитата из ссылки подсвечивается, даже если на неё больше ничего не ссылается.
  const ranges = useMemo(
    () =>
      findQuoteRanges(
        source.content,
        mark ? [...marks, { quote: mark, kind: 'about', ref: '' }] : marks,
      ),
    [source.content, marks, mark],
  )
  const parts = useMemo(() => splitByRanges(source.content, ranges), [source.content, ranges])
  const counts = { about: 0, evidence: 0, trace: 0 }
  for (const range of ranges) counts[range.kind] += 1

  const target = useMemo(() => {
    if (!mark) return undefined
    const [hit] = findQuoteRanges(source.content, [{ quote: mark, kind: 'about', ref: 'target' }])
    return hit
  }, [mark, source.content])

  // Открыли по цитате — прокручиваем к ней, когда панель уже выехала.
  useEffect(() => {
    if (!target) return
    const timer = setTimeout(() => {
      bodyRef.current
        ?.querySelector('[data-target="true"]')
        ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }, 260)
    return () => clearTimeout(timer)
  }, [target])

  const labelFor = (range: QuoteRange) => {
    if (range.kind === 'trace') return 'Элемент схемы'
    const question = project.questions.find((item) => item.id === range.ref)
    return question ? `${question.code}: ${question.text}` : 'Цитата'
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
              onCheckedChange={(active) => update.mutate({ id: source.id, active })}
            />
            <span className="flex-1" />
            {source.kind !== 'answer' && source.status === 'ready' && (
              <Button leadingIcon="pencil" onClick={() => setEditing(true)}>
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
                <Tooltip key={part.start} content={labelFor(part.range)}>
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
                </Tooltip>
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
