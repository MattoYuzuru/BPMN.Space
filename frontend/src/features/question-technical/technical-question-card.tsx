import { useState } from 'react'
import {
  QUESTION_ACTION,
  QUESTION_KIND,
  type Question,
  type QuestionActionKind,
  useQuestionTechnicalAction,
} from '@/entities/question'
import type { RunBudget } from '@/entities/run'
import { Badge, Button, Card, Icon } from '@/shared/ui'
import { RaiseBudgetDialog } from './budget-dialog'

/**
 * Карточка технического вопроса (RFC-0006): вопрос к материалам и запуску с действиями
 * вместо текстового ответа. Блокирующий вопрос держит прогон в `waiting`.
 */
export function TechnicalQuestionCard({
  question,
  projectId,
  budget,
  canEdit = true,
  onOpenSettings,
  onAction,
}: {
  question: Question
  projectId?: string
  /** Текущий бюджет ждущего прогона: показывается и поднимается вместе с обоими лимитами. */
  budget?: RunBudget | null
  /** Без права правки действия не показываем: сервер всё равно откажет. */
  canEdit?: boolean
  /** «Открыть настройки» выполняет экран: серверных изменений у действия нет. */
  onOpenSettings?: () => void
  /** В образцах стилгайда действие не уходит на сервер. */
  onAction?: (kind: QuestionActionKind) => void
}) {
  const action = useQuestionTechnicalAction(projectId ?? '')
  const [budgetOpen, setBudgetOpen] = useState(false)
  const kind = QUESTION_KIND[question.kind]
  const run = (kind: keyof typeof QUESTION_ACTION, budget?: RunBudget | null) =>
    action.mutate({ question, action: kind, budget })
  const actions = question.actions ?? []

  return (
    <Card
      variant="outline"
      padding="sm"
      data-question-id={question.id}
      aria-label={`Технический вопрос ${question.code}`}
      className="flex flex-col gap-2.5 border-amber/35"
    >
      <div className="flex items-center gap-2">
        <span className="shrink-0 whitespace-nowrap type-code text-fg-subtle">{question.code}</span>
        <span className="flex min-w-0 items-center gap-1 type-caption text-fg-muted">
          <Icon name={kind.icon} size={14} className="shrink-0 text-fg-subtle" />
          <span className="truncate">{kind.label}</span>
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1">
          {question.blocking && (
            <Badge tone="amber" icon="clock">
              Блокирует прогон
            </Badge>
          )}
          {question.status !== 'open' && (
            <Badge tone="neutral" variant="outline">
              Снят
            </Badge>
          )}
        </span>
      </div>

      <p className="type-body text-fg">{question.text}</p>

      {question.status === 'open' && canEdit && actions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {actions.map((item) => {
            const style = QUESTION_ACTION[item.kind]
            return (
              <Button
                key={item.kind}
                size="sm"
                variant={style.variant}
                leadingIcon={style.icon}
                loading={action.isPending && action.variables?.action === item.kind}
                disabled={action.isPending}
                onClick={() => {
                  if (onAction) {
                    onAction(item.kind)
                    return
                  }
                  if (item.kind === 'open_settings') onOpenSettings?.()
                  else if (item.kind === 'raise_budget') setBudgetOpen(true)
                  else run(item.kind)
                }}
              >
                {item.label}
              </Button>
            )
          })}
        </div>
      )}

      <RaiseBudgetDialog
        open={budgetOpen}
        onOpenChange={setBudgetOpen}
        current={budget ?? null}
        pending={action.isPending}
        onSubmit={(budget) => {
          setBudgetOpen(false)
          run('raise_budget', budget)
        }}
      />
    </Card>
  )
}
