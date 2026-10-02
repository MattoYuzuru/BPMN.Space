import { type FormEvent, useState } from 'react'
import { useAddTextSource } from '@/entities/source'
import { VoiceCapture } from '@/features/voice-record/voice-capture'
import { formatDate, formatTime } from '@/shared/lib/format'
import { Button, Dialog, DialogClose, DialogContent, Field, Input, Textarea } from '@/shared/ui'

interface DialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Текстовый источник: регламент, заметка, выдержка из письма. */
export function AddTextDialog({ projectId, open, onOpenChange }: DialogProps) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState<string>()
  const add = useAddTextSource(projectId)

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
      <DialogContent title="Текстовый источник" size="lg" aria-describedby={undefined}>
        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <Field label="Название" optional>
            <Input
              value={title}
              placeholder="Регламент, заметка со встречи, письмо"
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>
          <Field label="Текст" error={error}>
            <Textarea
              autoFocus
              value={content}
              minRows={8}
              maxRows={18}
              placeholder="Вставьте описание процесса: кто, что и в каком порядке делает"
              onChange={(event) => {
                setContent(event.target.value)
                if (error) setError(undefined)
              }}
            />
          </Field>
          <div className="-mx-5 -mb-5 mt-1 flex justify-end gap-2 border-t border-border px-5 py-3.5">
            <DialogClose asChild>
              <Button variant="ghost">Отмена</Button>
            </DialogClose>
            <Button type="submit" variant="primary" leadingIcon="plus" loading={add.isPending}>
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
        onOpenAutoFocus={(event) => event.preventDefault()}
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
