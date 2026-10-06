import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import {
  QUESTION_KIND,
  QUESTION_STATUS,
  type Question,
  SEVERITY,
  useQuestionAction,
} from '@/entities/question'
import { diagramElements, elementTypeLabel } from '@/entities/version'
import { AnswerComposer } from '@/features/answer-question/answer-composer'
import { formatDate, formatTime } from '@/shared/lib/format'
import {
  AssumptionFrame,
  Badge,
  Button,
  Icon,
  type IconName,
  Sheet,
  SheetContent,
} from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'
import { QuoteLink } from './quote-link'

/** Вопрос детально: цитаты, элементы схемы, ответ текстом или голосом, история. */
export function QuestionSheet() {
  const { project } = useWorkspace()
  const id = useWorkspaceUi((state) => state.questionSheet)
  const open = useWorkspaceUi((state) => state.openQuestionSheet)
  const question = project.questions.find((item) => item.id === id)
  return (
    <Sheet open={Boolean(question)} onOpenChange={(next) => !next && open(null)}>
      {question && <QuestionDetail question={question} />}
    </Sheet>
  )
}

function QuestionDetail({ question }: { question: Question }) {
  const { project, canEdit, selectQuestion, focusElements, versions } = useWorkspace()
  const close = useWorkspaceUi((state) => state.openQuestionSheet)
  const action = useQuestionAction(project.id)
  const latest = project.latest_version
  const xml = useQuery({ ...versions.detail(latest?.id ?? ''), enabled: Boolean(latest) })
  const elements = xml.data ? diagramElements(xml.data.xml) : null
  const kind = QUESTION_KIND[question.kind]
  const severity = SEVERITY[question.severity]
  const status = QUESTION_STATUS[question.status]
  const sourceOf = (sourceId?: string) => project.sources.find((source) => source.id === sourceId)

  const showOnDiagram = (ids: readonly string[]) => {
    selectQuestion(question.id)
    close(null)
    // Даём панели закрыться, чтобы схема была видна во время перелёта.
    setTimeout(() => focusElements(ids), 180)
  }

  return (
    <SheetContent
      size="md"
      title={
        <span className="flex items-center gap-2">
          <span className="type-code text-fg-subtle">{question.code}</span>
          {kind.label}
        </span>
      }
      footer={
        <>
          {canEdit && question.status === 'open' && (
            <Button
              variant="ghost"
              leadingIcon="eye-off"
              onClick={() => action.mutate({ question, action: { type: 'ignore' } })}
            >
              Игнорировать
            </Button>
          )}
          {canEdit && (question.status === 'ignored' || question.status === 'answered') && (
            <Button
              variant="ghost"
              leadingIcon="undo"
              onClick={() => action.mutate({ question, action: { type: 'reopen' } })}
            >
              Вернуть
            </Button>
          )}
          {question.element_ids.length > 0 && (
            <Button leadingIcon="locate" onClick={() => showOnDiagram(question.element_ids)}>
              Показать на схеме
            </Button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={severity.tone} variant="outline">
              {severity.label}
            </Badge>
            <Badge tone={status.tone} dot>
              {status.label}
            </Badge>
          </div>
          <p className="type-heading text-fg">{question.text}</p>
        </div>

        {(question.about || question.evidence) && (
          <Section title="Цитаты" icon="quote">
            {question.about && (
              <QuoteLink
                clamp={false}
                quote={question.about}
                source={sourceOf(question.about.source_id)}
              />
            )}
            {question.evidence && (
              <QuoteLink
                clamp={false}
                tone={question.status === 'obsolete' ? 'about' : 'evidence'}
                quote={question.evidence}
                source={sourceOf(question.evidence.source_id)}
              />
            )}
          </Section>
        )}

        {question.element_ids.length > 0 && (
          <Section title="На схеме" icon="diagram">
            <div className="flex flex-wrap gap-1.5">
              {question.element_ids.map((elementId) => {
                const element = elements?.get(elementId)
                return (
                  <Button
                    key={elementId}
                    size="sm"
                    variant="secondary"
                    leadingIcon="locate"
                    onClick={() => showOnDiagram([elementId])}
                    className="max-w-full"
                  >
                    <span className="truncate">
                      {element?.name || (element ? elementTypeLabel(element.type) : elementId)}
                    </span>
                  </Button>
                )
              })}
            </div>
          </Section>
        )}

        {(question.status === 'open' || question.status === 'ignored') && (
          <AssumptionFrame
            label={question.status === 'ignored' ? 'Принято допущение' : 'Если не ответить'}
          >
            {question.assumption}
          </AssumptionFrame>
        )}

        {canEdit && question.status === 'open' && (
          <Section title="Ответ" icon="message-question">
            <AnswerComposer
              projectId={project.id}
              question={question}
              autoFocus={false}
              tourAnchored={false}
            />
          </Section>
        )}

        <Section title="История" icon="history">
          <History question={question} />
        </Section>
      </div>
    </SheetContent>
  )
}

function Section({
  title,
  icon,
  children,
}: {
  title: string
  icon: IconName
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <h3 className="flex items-center gap-1.5 type-label text-fg-muted">
        <Icon name={icon} size={14} />
        {title}
      </h3>
      {children}
    </section>
  )
}

function stamp(iso: string) {
  const date = new Date(iso)
  return `${formatDate(date)}, ${formatTime(date)}`
}

function History({ question }: { question: Question }) {
  const { project } = useWorkspace()
  const evidenceSource = project.sources.find((s) => s.id === question.evidence?.source_id)
  const items: { icon: IconName; tone: string; title: ReactNode; at?: string }[] = [
    {
      icon: 'sparkles',
      tone: 'text-accent-fg',
      title: 'Вопрос задан анализом',
      at: question.created_at,
    },
  ]
  if (question.answer) {
    items.push({
      icon: 'message-question',
      tone: 'text-accent-fg',
      title: (
        <span className="flex flex-col gap-1">
          Аналитик ответил
          <span className="type-ui text-fg-muted">{question.answer.text}</span>
        </span>
      ),
    })
  }
  if (question.status === 'ignored') {
    items.push({
      icon: 'assumption',
      tone: 'text-amber-fg',
      title: 'Принято допущение',
      at: question.updated_at,
    })
  }
  if (question.status === 'resolved') {
    items.push({
      icon: 'circle-check',
      tone: 'text-success-fg',
      title: evidenceSource ? `Решён по источнику «${evidenceSource.title}»` : 'Решён',
      at: question.updated_at,
    })
  }
  if (question.status === 'obsolete') {
    items.push({
      icon: 'history',
      tone: 'text-fg-muted',
      title: 'Предмет вопроса больше не относится к текущему процессу',
      at: question.updated_at,
    })
  }
  return (
    <ol className="flex flex-col gap-3">
      {items.map((item, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: порядок событий фиксирован
        <li key={index} className="flex gap-2.5">
          <Icon name={item.icon} size={16} className={`mt-0.5 shrink-0 ${item.tone}`} />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5 type-ui text-fg">
            {item.title}
            {item.at && (
              <time dateTime={item.at} className="type-caption text-fg-subtle">
                {stamp(item.at)}
              </time>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
