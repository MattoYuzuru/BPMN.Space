import { useMutation } from '@tanstack/react-query'
import { type ReactNode, useEffect, useRef } from 'react'
import { errorMessage } from '@/shared/api/client'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { IconButton, toast, VoiceInput } from '@/shared/ui'
import { isNoSpeechError, NO_SPEECH_MESSAGE, transcribeAudio } from './api'
import { useVoiceRecorder } from './use-voice-recorder'
import { BLOCKED } from './voice-capture'

export interface VoiceDictationProps {
  children: ReactNode
  /** Остановка возвращает текст в черновик, не отправляя форму. */
  onText: (text: string) => void
  /** Прямая отправка после распознавания — для ответа на вопрос. */
  onSubmit?: (text: string) => void
  label?: string
  sendLabel?: string
  onActiveChange?: (active: boolean) => void
}

export function appendDictation(draft: string, text: string): string {
  return [draft.trim(), text.trim()].filter(Boolean).join('\n')
}

/** Диктовка в той же рамке, что и поле: отмена сохраняет черновик, остановка возвращает текст. */
export function VoiceDictation({
  children,
  onText,
  onSubmit,
  label = 'Надиктовать',
  sendLabel = 'Распознать и отправить ответ',
  onActiveChange,
}: VoiceDictationProps) {
  const recorder = useVoiceRecorder()
  const transcribe = useMutation({
    mutationFn: ({ blob, signal }: { blob: Blob; signal: AbortSignal }) =>
      transcribeAudio(blob, signal),
  })
  const root = useRef<HTMLFieldSetElement>(null)
  const operation = useRef<AbortController | null>(null)
  const handled = useRef<Blob | null>(null)
  const intent = useRef<'draft' | 'send'>('draft')
  const wasActive = useRef(false)
  const active = ['requesting', 'recording', 'recorded'].includes(recorder.state.status)

  const cancel = () => {
    operation.current?.abort()
    operation.current = null
    transcribe.reset()
    recorder.cancel()
  }

  useEffect(() => {
    onActiveChange?.(active)
    if (wasActive.current && !active) root.current?.querySelector('textarea')?.focus()
    if (!wasActive.current && active) root.current?.focus()
    wasActive.current = active
  }, [active, onActiveChange])

  useEffect(() => {
    // Остановка недоступна при распознавании: возвращаем фокус в группу с доступной отменой.
    if (recorder.state.status === 'recorded') root.current?.focus()
  }, [recorder.state.status])

  // Поздний ответ после отмены или закрытия формы не меняет черновик и не отправляет ответ.
  useEffect(() => () => operation.current?.abort(), [])

  useEffect(() => {
    const state = recorder.state
    if (state.status !== 'recorded' || handled.current === state.blob) return
    handled.current = state.blob
    const controller = new AbortController()
    operation.current = controller
    transcribe.mutate(
      { blob: state.blob, signal: controller.signal },
      {
        onSuccess: ({ text }) => {
          if (controller.signal.aborted) return
          recorder.cancel()
          if (intent.current === 'send' && onSubmit) onSubmit(text.trim())
          else onText(text.trim())
        },
        onError: (error) => {
          if (controller.signal.aborted) return
          recorder.cancel()
          if (isNoSpeechError(error)) {
            toast.warning('Речь не распознана', { description: NO_SPEECH_MESSAGE })
          } else {
            toast.error('Не удалось распознать голос', { description: errorMessage(error) })
          }
        },
      },
    )
  }, [recorder.state, recorder.cancel, transcribe.mutate, onText, onSubmit])

  useEffect(() => {
    if (recorder.state.status !== 'blocked') return
    const info = BLOCKED[recorder.state.reason]
    toast.warning(info.title, { description: info.description })
  }, [recorder.state])

  return (
    <fieldset
      ref={root}
      tabIndex={-1}
      aria-label="Ввод текста или запись голоса"
      className="relative min-w-0 outline-none"
      onKeyDown={(event) => {
        if (active && event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          cancel()
        }
      }}
    >
      <div hidden={active}>{children}</div>
      {active ? (
        <div {...tourAnchor(TOUR_ANCHORS.voiceCapture)}>
          <VoiceInput
            phase={
              recorder.state.status === 'requesting'
                ? 'requesting'
                : recorder.state.status === 'recording'
                  ? 'recording'
                  : 'transcribing'
            }
            levels={recorder.levels}
            elapsed={
              recorder.state.status === 'recorded' ? recorder.state.durationSec : recorder.elapsed
            }
            onCancel={cancel}
            onStop={() => {
              intent.current = 'draft'
              recorder.stop()
            }}
            onSend={
              onSubmit
                ? () => {
                    intent.current = 'send'
                    recorder.stop()
                  }
                : undefined
            }
            sendLabel={sendLabel}
          />
        </div>
      ) : (
        <IconButton
          icon="microphone"
          label={label}
          size="sm"
          className="absolute top-1.5 right-1.5"
          onClick={() => {
            intent.current = 'draft'
            transcribe.reset()
            void recorder.start()
          }}
        />
      )}
    </fieldset>
  )
}
