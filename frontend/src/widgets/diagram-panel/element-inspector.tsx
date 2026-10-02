import { QUESTION_STATUS } from '@/entities/question'
import { type DiagramElement, elementTypeLabel, type VersionDetail } from '@/entities/version'
import { cn } from '@/shared/lib/cn'
import { AssumptionFrame, Badge, Card, Icon, IconButton } from '@/shared/ui'
import { QuoteLink } from '@/widgets/questions-panel/quote-link'
import { useWorkspace } from '@/widgets/workspace/model'

/**
 * Карточка элемента схемы по клику: откуда он взялся (цитата-трассировка), какие вопросы
 * его касаются и на каком допущении он построен.
 */
export function ElementInspector({
  elementId,
  element,
  version,
  onClose,
}: {
  elementId: string
  element?: DiagramElement
  version: VersionDetail
  onClose: () => void
}) {
  const { project, selectQuestion, selectedQuestionId } = useWorkspace()
  const trace = version.trace[elementId]
  const source = trace && project.sources.find((item) => item.id === trace.source_id)
  const questions = project.questions.filter((question) => question.element_ids.includes(elementId))
  const assumptions = version.report.assumptions.filter((item) => item.element_id === elementId)

  return (
    <Card
      variant="elevated"
      padding="none"
      className="w-80 overflow-hidden bg-surface-raised shadow-lg"
      aria-label="Элемент схемы"
      role="dialog"
    >
      <div className="flex items-start gap-2 border-b border-border px-4 pt-3 pb-2.5">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="type-caption text-fg-subtle">
            {element ? elementTypeLabel(element.type) : 'Элемент'}
          </span>
          <span className="type-subheading text-fg">
            {element?.name || <span className="type-code text-fg-muted">{elementId}</span>}
          </span>
        </div>
        <IconButton icon="x" size="sm" label="Закрыть" tooltip={false} onClick={onClose} />
      </div>
      <div className="flex max-h-80 flex-col gap-3 px-4 py-3">
        {trace ? (
          <div className="flex flex-col gap-1.5">
            <span className="type-label text-fg-muted">Откуда в схеме</span>
            <QuoteLink quote={trace} source={source} />
          </div>
        ) : (
          <span className="flex items-center gap-1.5 type-caption text-fg-subtle">
            <Icon name="pencil" size={14} />
            Добавлен вручную или без цитаты
          </span>
        )}
        {assumptions.length > 0 && (
          <AssumptionFrame>{assumptions.map((item) => item.text).join('. ')}</AssumptionFrame>
        )}
        {questions.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="type-label text-fg-muted">Вопросы</span>
            {questions.map((question) => (
              <a
                key={question.id}
                href={`?question=${question.id}`}
                onClick={(event) => {
                  event.preventDefault()
                  selectQuestion(question.id)
                }}
                className={cn(
                  '-mx-2 flex items-start gap-2 rounded-md px-2 py-1.5 outline-none transition-colors duration-base hover:bg-hover focus-visible:ring-2 focus-visible:ring-focus-ring',
                  selectedQuestionId === question.id && 'bg-accent-subtle/70',
                )}
              >
                <span className="type-code pt-0.5 text-fg-subtle">{question.code}</span>
                <span className="line-clamp-2 flex-1 type-ui text-fg">{question.text}</span>
                <Badge tone={QUESTION_STATUS[question.status].tone} dot className="mt-0.5">
                  {question.status === 'open'
                    ? 'Открыт'
                    : question.status === 'resolved'
                      ? 'Решён'
                      : question.status === 'ignored'
                        ? 'Допущение'
                        : 'Ответ'}
                </Badge>
              </a>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}
