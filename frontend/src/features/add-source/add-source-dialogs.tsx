import { type FormEvent, useRef, useState } from 'react'
import { useAddTextSource } from '@/entities/source'
import { VoiceCapture } from '@/features/voice-record/voice-capture'
import { formatDate, formatTime } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  Field,
  Input,
  SuggestedTextarea,
} from '@/shared/ui'

interface DialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Название источника, которое подставляется вместе с принятой подсказкой. */
export const SUGGESTED_TEXT_TITLE = 'Описание процесса'

/**
 * Текстовый источник: регламент, заметка, выдержка из письма. Если передана `suggestion`, пустое
 * поле «Текст» предлагает её как автодополнение (обучение даёт подсказку, остальные — нет).
 */
export function AddTextDialog({
  projectId,
  open,
  onOpenChange,
  suggestion,
}: DialogProps & { suggestion?: string | null }) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState<string>()
  const add = useAddTextSource(projectId)
  const contentRef = useRef<HTMLTextAreaElement>(null)

  const reset = () => {
    setTitle('')
    setContent('')
    setError(undefined)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (content.trim().length < 20) {
      setError('Добавьте хотя бы пару предложений — из них модель извлекает шаги и участников')
      return
    }
    add.mutate(
      { kind: 'text', title: title.trim() || null, content: content.trim() },
      {
        onSuccess: () => {
          onOpenChange(false)
          reset()
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Текстовый источник"
        size="lg"
        aria-describedby={undefined}
        // С подсказкой человек сразу принимает её (Tab) или пишет сам: фокус на поле «Текст».
        onOpenAutoFocus={(event) => {
          if (!suggestion) return
          event.preventDefault()
          contentRef.current?.focus()
        }}
      >
        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <Field label="Название" optional>
            <Input
              value={title}
              placeholder="Регламент, заметка со встречи, письмо"
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>
          <Field label="Текст" error={error}>
            <SuggestedTextarea
              ref={contentRef}
              autoFocus
              value={content}
              minRows={8}
              maxRows={18}
              placeholder="Вставьте описание процесса: кто, что и в каком порядке делает"
              suggestion={suggestion}
              onInsert={() => setTitle((current) => current || SUGGESTED_TEXT_TITLE)}
              onValueChange={(next) => {
                setContent(next)
                if (error) setError(undefined)
              }}
              {...tourAnchor(TOUR_ANCHORS.sourceTextContent)}
            />
          </Field>
          <div className="-mx-5 -mb-5 mt-1 flex justify-end gap-2 border-t border-border px-5 py-3.5">
            <DialogClose asChild>
              <Button variant="ghost">Отмена</Button>
            </DialogClose>
            <Button
              type="submit"
              variant="primary"
              leadingIcon="plus"
              loading={add.isPending}
              {...tourAnchor(TOUR_ANCHORS.sourceTextSubmit)}
            >
              Добавить источник
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function defaultVoiceTitle(now = new Date()) {
  return `Голосовая заметка, ${formatDate(now)} ${formatTime(now)}`
}

/** Голосовой источник: запись → расшифровка → правка → источник kind=voice. */
export function AddVoiceDialog({ projectId, open, onOpenChange }: DialogProps) {
  const [title, setTitle] = useState(defaultVoiceTitle)
  const add = useAddTextSource(projectId)
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setTitle(defaultVoiceTitle())
        onOpenChange(next)
      }}
    >
      <DialogContent
        title="Голосовая заметка"
        size="md"
        aria-describedby={undefined}
        // Запись стартует сама; фокус на крестике отвлекал бы от таймера.
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          ;(event.currentTarget as HTMLElement | null)?.focus()
        }}
      >
        {open && (
          <VoiceCapture
            autoStart
            submitLabel="Добавить как источник"
            pending={add.isPending}
            extraFields={
              <Field label="Название">
                <Input value={title} onChange={(event) => setTitle(event.target.value)} />
              </Field>
            }
            onSubmit={({ text, durationSec }) =>
              add.mutate(
                {
                  kind: 'voice',
                  title: title.trim() || defaultVoiceTitle(),
                  content: text,
                  duration_sec: durationSec,
                },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
