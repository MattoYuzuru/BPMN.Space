import { useState } from 'react'
import { QUESTION_KIND, type Question, SEVERITY, useQuestionAction } from '@/entities/question'
import type { Source } from '@/entities/source'
import { AnswerComposer } from '@/features/answer-question/answer-composer'
import { cn } from '@/shared/lib/cn'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { AssumptionFrame, Badge, Button, Card, Icon, IconButton } from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'
import { QuoteLink } from './quote-link'

const SEVERITY_STRIP = {
  blocker: 'bg-danger',
  major: 'bg-amber',
  minor: 'bg-border-strong',
} as const

export interface QuestionCardProps {
  question: Question
  /** Вопрос только что решён прогоном: показываем доказательство перед уходом во вкладку «Решено». */
  settling?: boolean
  /** Появился в последнем прогоне. */
  fresh?: boolean
}

/**
 * Карточка вопроса: полоса важности, тип, текст, цитата-повод, допущение и действия.
 * Выбранная карточка светится током, её элементы подсвечены на схеме.
 */
export function QuestionCard({ question, settling = false, fresh = false }: QuestionCardProps) {
  const { project, canEdit, selectedQuestionId, selectQuestion, focusElements } = useWorkspace()
  const openSheet = useWorkspaceUi((state) => state.openQuestionSheet)
  const action = useQuestionAction(project.id)
  const [answering, setAnswering] = useState(false)
  const selected = selectedQuestionId === question.id
  const kind = QUESTION_KIND[question.kind]
  const severity = SEVERITY[question.severity]
  const sourceOf = (id?: string): Source | undefined =>
    project.sources.find((source) => source.id === id)
  const resolved = question.status === 'resolved' || settling
  const obsolete = question.status === 'obsolete'
  const hasElements = question.element_ids.length > 0

  return (
    <Card
      padding="none"
      glow={selected && !resolved && !obsolete}
      data-question={question.code}
      data-question-id={question.id}
      aria-current={selected || undefined}
      onClick={(event) => {
        // Клик по свободному месту карточки выбирает вопрос; кнопки и ссылки работают сами.
        if ((event.target as HTMLElement).closest('a, button, textarea, input, [role="button"]')) {
          return
        }
        selectQuestion(selected ? undefined : question.id, { focus: !selected })
      }}
      className={cn(
        'group/question relative cursor-default overflow-hidden transition-[border-color,box-shadow,background-color] duration-base ease-soft',
        !selected && 'hover:border-border-strong',
        settling && 'border-success/50 bg-success-subtle/40',
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'absolute inset-y-0 left-0 w-0.5 transition-colors duration-slow',
          obsolete
            ? 'bg-border-strong'
            : resolved
              ? 'bg-success'
              : question.status === 'answered'
                ? 'bg-accent'
                : SEVERITY_STRIP[question.severity],
        )}
      />
      <div className="flex flex-col gap-2.5 py-3 pr-3 pl-4">
        <div className="flex items-center gap-2">
          <span className="shrink-0 whitespace-nowrap type-code text-fg-subtle">
            {question.code}
          </span>
          <span className="flex min-w-0 items-center gap-1 type-caption text-fg-muted">
            <Icon name={kind.icon} size={14} className="shrink-0 text-fg-subtle" />
            <span className="truncate">{kind.label}</span>
          </span>
          <span className="ml-auto flex shrink-0 items-center gap-1">
            {fresh && !resolved && !obsolete && (
              <Badge tone="accent" icon="sparkles">
                Новый
              </Badge>
            )}
            {obsolete ? (
              <Badge tone="neutral" variant="outline">
                Неактуален
              </Badge>
            ) : resolved ? (
              <Badge tone="success" icon="circle-check">
                Решён
              </Badge>
            ) : question.status === 'answered' ? (
              <Badge tone="accent" variant="outline" icon="message-question">
                Ответ получен
              </Badge>
            ) : (
              <Badge tone={severity.tone} variant="outline">
                {severity.label}
              </Badge>
            )}
          </span>
        </div>

        <p className="type-body text-fg">{question.text}</p>

        {(resolved || obsolete) && question.evidence ? (
          <QuoteLink
            quote={question.evidence}
            source={sourceOf(question.evidence.source_id)}
            tone={obsolete ? 'about' : 'evidence'}
          />
        ) : (
          question.about && (
            <QuoteLink quote={question.about} source={sourceOf(question.about.source_id)} />
          )
        )}

        {question.status === 'answered' && question.answer && (
          <div className="flex flex-col gap-1 rounded-md bg-accent-subtle/60 px-3 py-2">
            <span className="flex items-center gap-1.5 type-label text-accent-fg">
              <Icon name="message-question" size={14} />
              Ваш ответ
            </span>
            <p className="line-clamp-4 type-ui text-fg">{question.answer.text}</p>
            <span className="type-caption text-fg-muted">Ответ учтётся при следующем анализе</span>
          </div>
        )}

        {(question.status === 'open' || question.status === 'ignored') && !settling && (
          <AssumptionFrame
            label={question.status === 'ignored' ? 'Принято допущение' : 'Допущение'}
            actions={
              question.status === 'ignored' && canEdit ? (
                <Button
                  size="sm"
                  variant="ghost"
                  leadingIcon="undo"
                  onClick={() => action.mutate({ question, action: { type: 'reopen' } })}
                >
                  Вернуть
                </Button>
              ) : undefined
            }
          >
            {question.assumption}
          </AssumptionFrame>
        )}

        {answering && canEdit ? (
          <AnswerComposer
            projectId={project.id}
            question={question}
            onDone={() => setAnswering(false)}
            onCancel={() => setAnswering(false)}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-1">
            {canEdit && question.status === 'answered' && (
              <Button
                size="sm"
                variant="ghost"
                leadingIcon="undo"
                onClick={() => action.mutate({ question, action: { type: 'reopen' } })}
              >
                Вернуть
              </Button>
            )}
            {canEdit && question.status === 'open' && (
              <>
                <Button
                  size="sm"
                  variant="secondary"
                  leadingIcon="message-question"
                  onClick={() => {
                    setAnswering(true)
                    selectQuestion(question.id)
                  }}
                  {...tourAnchor(TOUR_ANCHORS.questionAnswer)}
                >
                  Ответить
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  leadingIcon="eye-off"
                  onClick={() => action.mutate({ question, action: { type: 'ignore' } })}
                  {...tourAnchor(TOUR_ANCHORS.questionIgnore)}
                >
                  Игнорировать
                </Button>
              </>
            )}
            <div className="ml-auto flex items-center gap-0.5">
              {hasElements && (
                <IconButton
                  icon="locate"
                  size="sm"
                  label="Показать на схеме"
                  onClick={() => {
                    selectQuestion(question.id)
                    focusElements(question.element_ids)
                  }}
                />
              )}
              <IconButton
                icon="arrow-up-right"
                size="sm"
                label="Подробнее"
                onClick={() => openSheet(question.id)}
              />
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
