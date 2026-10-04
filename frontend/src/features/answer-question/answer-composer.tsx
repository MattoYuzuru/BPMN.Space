import { type FormEvent, useState } from 'react'
import { type Question, useQuestionAction } from '@/entities/question'
import { VoiceDictation } from '@/features/voice-record/voice-dictation'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Button, Textarea } from '@/shared/ui'

export interface AnswerComposerProps {
  projectId: string
  question: Question
  onDone?: () => void
  onCancel?: () => void
  autoFocus?: boolean
  /** Ставить обучающий якорь на «Отправить ответ»; у композера в листе вопроса — нет. */
  tourAnchored?: boolean
}

/**
 * Ответ на вопрос: текстом или голосом (запись -> расшифровка -> правка). Отправка
 * оптимистичная — карточка сразу переходит в «ответ учтётся при анализе».
 */
export function AnswerComposer({
  projectId,
  question,
  onDone,
  onCancel,
  autoFocus = true,
  tourAnchored = true,
}: AnswerComposerProps) {
  const [text, setText] = useState('')
  const action = useQuestionAction(projectId)

  const send = (value: string) => {
    if (!value.trim()) return
    action.mutate({ question, action: { type: 'answer', text: value.trim() } })
    setText('')
    onDone?.()
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    send(text)
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 animate-fade-in">
      <div className="relative">
        <Textarea
          autoFocus={autoFocus}
          value={text}
          minRows={2}
          maxRows={8}
          aria-label={`Ответ на вопрос ${question.code}`}
          placeholder="Ответьте своими словами или надиктуйте"
          className="pr-10"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') onCancel?.()
            // Ctrl+Enter или ⌘Enter — отправить, как в мессенджерах.
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault()
              send(text)
            }
          }}
        />
        <VoiceDictation
          label="Ответить голосом"
          submitLabel="Отправить ответ"
          submitIcon="send"
          className="absolute top-1.5 right-1.5"
          onText={send}
        />
      </div>
      <div className="flex items-center justify-end gap-2">
        <div className="flex gap-1.5">
          {onCancel && (
            <Button size="sm" variant="ghost" onClick={onCancel}>
              Отмена
            </Button>
          )}
          <Button
            size="sm"
            type="submit"
            variant="primary"
            leadingIcon="send"
            disabled={!text.trim()}
            {...(tourAnchored ? tourAnchor(TOUR_ANCHORS.answerSubmit) : {})}
          >
            Отправить ответ
          </Button>
        </div>
      </div>
    </form>
  )
}
