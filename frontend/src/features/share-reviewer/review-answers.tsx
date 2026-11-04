import { useState } from 'react'
import { isTechnical, type Question } from '@/entities/question'
import { shareAnswerError, useAnswerSharedQuestion, useShareQuestions } from '@/entities/share'
import { Badge, Button, Card, Field, Icon, Skeleton, Textarea, toast } from '@/shared/ui'

const MAX_ANSWER_CHARS = 20_000

/**
 * Ответы проверяющего прямо по ссылке, без аккаунта. Ссылка — удостоверение: сервер пишет
 * провенанс `via=review` и id ссылки, область ограничена её дорожками, чужие вопросы — 404.
 */
export function ReviewAnswers({ token }: { token: string }) {
  const questions = useShareQuestions(token)
  const items = (questions.data ?? []).filter(
    (question) => question.status === 'open' && !isTechnical(question),
  )
  return (
    <section
      aria-label="Вопросы области проверки"
      className="shrink-0 border-b border-border bg-bg-subtle px-4 py-3 wide:px-5"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="type-label text-fg">Вопросы области проверки</h3>
        {items.length > 0 && (
          <span className="type-caption text-fg-subtle" data-numeric>
            {items.length} без ответа
          </span>
        )}
      </div>
      {questions.isPending && <Skeleton className="mt-2 h-20 w-full" />}
      {questions.isError && (
        <p className="mt-2 flex items-center gap-2 type-caption text-fg-muted" role="alert">
          <Icon name="alert-circle" size={14} />
          Вопросы не загрузились. Ответить по ссылке можно, когда список появится.
          <Button
            size="sm"
            variant="ghost"
            leadingIcon="refresh"
            onClick={() => void questions.refetch()}
          >
            Повторить
          </Button>
        </p>
      )}
      {!questions.isPending && !questions.isError && items.length === 0 && (
        <p className="mt-1 type-caption text-fg-muted">Открытых вопросов в области проверки нет.</p>
      )}
      {items.length > 0 && (
        <ul className="mt-2 flex flex-col gap-2">
          {items.map((question) => (
            <li key={question.id}>
              <ReviewAnswerCard token={token} question={question} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ReviewAnswerCard({ token, question }: { token: string; question: Question }) {
  const answer = useAnswerSharedQuestion(token)
  const [text, setText] = useState('')
  const [error, setError] = useState<string>()
  const trimmed = text.trim()
  const tooLong = trimmed.length > MAX_ANSWER_CHARS
  const empty = trimmed.length === 0

  const submit = () => {
    if (empty) {
      setError('Напишите ответ — пустой ответ сервер не примет.')
      return
    }
    if (tooLong) {
      setError(`Ответ длиннее ${MAX_ANSWER_CHARS.toLocaleString('ru-RU')} символов.`)
      return
    }
    setError(undefined)
    answer.mutate(
      { questionId: question.id, text: trimmed },
      {
        onSuccess: () => {
          setText('')
          toast.success('Ответ отправлен', {
            description: 'Он отмечен как ответ по ссылке проверки.',
          })
        },
        onError: (cause) => setError(shareAnswerError(cause)),
      },
    )
  }

  return (
    <Card variant="outline" padding="sm" className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral" variant="outline">
          {question.code}
        </Badge>
        {question.severity !== 'minor' && (
          <Badge tone={question.severity === 'blocker' ? 'danger' : 'amber'} variant="outline">
            {question.severity === 'blocker' ? 'Блокирует' : 'Важно'}
          </Badge>
        )}
      </div>
      <p className="type-ui text-fg">{question.text}</p>
      <p className="type-caption text-fg-subtle">
        Если ответа не будет — модель примет допущение: {question.assumption}
      </p>
      <Field
        label="Ваш ответ"
        hint="Ответ будет отмечен как ответ по ссылке проверки."
        error={error}
      >
        <Textarea
          value={text}
          minRows={2}
          maxRows={6}
          aria-label={`Ответ на вопрос ${question.code}`}
          placeholder="Что известно по этому вопросу"
          onChange={(event) => {
            setText(event.target.value)
            if (error) setError(undefined)
          }}
        />
      </Field>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 type-caption text-fg-subtle">
          <Icon name="users" size={14} />
          Проверяющий по ссылке, без входа
        </span>
        <Button
          size="sm"
          variant="primary"
          loading={answer.isPending}
          disabled={tooLong}
          onClick={submit}
        >
          Отправить ответ
        </Button>
      </div>
    </Card>
  )
}
