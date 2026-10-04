import { AnimatePresence, m } from 'motion/react'
import { type ReactNode, useEffect, useState } from 'react'
import { errorMessage } from '@/shared/api/client'
import { formatClock } from '@/shared/lib/format'
import { softTransition } from '@/shared/lib/motion'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { AudioLevel, Button, Field, Icon, Progress, Textarea } from '@/shared/ui'
import { useTranscribe } from './api'
import { type RecorderState, useVoiceRecorder } from './use-voice-recorder'

const BLOCKED: Record<
  Extract<RecorderState, { status: 'blocked' }>['reason'],
  { title: string; description: string }
> = {
  denied: {
    title: 'Нет доступа к микрофону',
    description:
      'Разрешите доступ в настройках сайта: значок слева от адреса, пункт «Микрофон». Затем повторите.',
  },
  missing: {
    title: 'Микрофон не найден',
    description: 'Подключите микрофон или гарнитуру и повторите.',
  },
  unsupported: {
    title: 'Браузер не умеет записывать звук',
    description: 'Откройте проект в свежем Chrome, Edge, Firefox или Яндекс Браузере.',
  },
  failed: {
    title: 'Запись не началась',
    description: 'Микрофон занят другим приложением или недоступен. Закройте его и повторите.',
  },
}

export interface VoiceCaptureResult {
  text: string
  durationSec: number
}

export interface VoiceCaptureProps {
  /** Кнопка завершения: «Добавить как источник», «Отправить ответ». */
  submitLabel: string
  submitIcon?: 'plus' | 'send'
  pending?: boolean
  onSubmit: (result: VoiceCaptureResult) => void
  /** Дополнительные поля над расшифровкой (название источника). */
  extraFields?: ReactNode
  /** Сразу начать запись при открытии. */
  autoStart?: boolean
  compact?: boolean
}

/**
 * Запись голоса целиком: запись с уровнем сигнала и таймером -> распознавание
 * (`POST /transcriptions`) -> правка расшифровки -> отправка.
 */
export function VoiceCapture({
  submitLabel,
  submitIcon = 'plus',
  pending = false,
  onSubmit,
  extraFields,
  autoStart = false,
  compact = false,
}: VoiceCaptureProps) {
  const recorder = useVoiceRecorder()
  const transcribe = useTranscribe()
  const [text, setText] = useState('')
  const [duration, setDuration] = useState(0)
  const { state } = recorder

  // biome-ignore lint/correctness/useExhaustiveDependencies: старт один раз при открытии
  useEffect(() => {
    if (autoStart) void recorder.start()
  }, [])

  // Запись остановлена -> сразу отправляем на распознавание.
  useEffect(() => {
    if (state.status !== 'recorded') return
    setDuration(state.durationSec)
    transcribe.mutate(state.blob, { onSuccess: (result) => setText(result.text) })
  }, [state, transcribe.mutate])

  const reviewing = state.status === 'recorded' && transcribe.isSuccess
  const transcribing = state.status === 'recorded' && transcribe.isPending
  const failed = state.status === 'recorded' && transcribe.isError

  const restart = () => {
    transcribe.reset()
    setText('')
    void recorder.start()
  }

  if (state.status === 'blocked') {
    const info = BLOCKED[state.reason]
    return (
      <div
        {...tourAnchor(TOUR_ANCHORS.voiceCapture)}
        className="flex flex-col items-center gap-3 rounded-lg border border-border bg-bg-subtle px-5 py-6 text-center animate-fade-in"
      >
        <span className="grid size-10 place-items-center rounded-full bg-danger-subtle text-danger-fg">
          <Icon name="microphone-off" size={20} />
        </span>
        <div className="flex max-w-xs flex-col gap-1">
          <span className="type-subheading text-fg">{info.title}</span>
          <p className="type-caption text-fg-muted">{info.description}</p>
        </div>
        {state.reason !== 'unsupported' && (
          <Button size="sm" onClick={() => void recorder.start()}>
            Повторить
          </Button>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div
        {...tourAnchor(TOUR_ANCHORS.voiceCapture)}
        className="relative flex flex-col gap-3 rounded-lg border border-border bg-bg-subtle px-4 pt-4 pb-3"
      >
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2 type-label text-fg-muted">
            {state.status === 'recording' ? (
              <span className="relative grid size-2.5 place-items-center">
                <span className="absolute inset-0 animate-breathe rounded-full bg-accent/40" />
                <span className="size-1.5 rounded-full bg-accent" />
              </span>
            ) : (
              <Icon name="microphone" size={14} />
            )}
            {state.status === 'recording'
              ? 'Идёт запись'
              : transcribing
                ? 'Распознаю речь'
                : reviewing
                  ? 'Запись распознана'
                  : 'Микрофон'}
          </span>
          <span className="type-code text-sm text-fg" data-numeric>
            {formatClock(state.status === 'recording' ? recorder.elapsed : duration)}
          </span>
        </div>
        <AudioLevel
          levels={recorder.levels}
          active={state.status === 'recording'}
          label="Уровень сигнала микрофона"
          bars={compact ? 32 : 48}
          className={compact ? 'h-10' : 'h-14'}
        />
        {transcribing && <Progress label="Распознавание речи" />}
      </div>

      <AnimatePresence mode="wait" initial={false}>
        {reviewing || failed ? (
          <m.div
            key="review"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0, transition: softTransition }}
            exit={{ opacity: 0 }}
            className="flex flex-col gap-4"
          >
            {extraFields}
            {failed ? (
              <div className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2.5 type-ui text-danger-fg">
                <Icon name="alert-circle" size={16} className="mt-0.5" />
                <span className="flex-1">
                  Не удалось распознать голос. {errorMessage(transcribe.error, '')}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => state.status === 'recorded' && transcribe.mutate(state.blob)}
                >
                  Повторить
                </Button>
              </div>
            ) : (
              <Field label="Расшифровка">
                <Textarea
                  value={text}
                  minRows={compact ? 3 : 4}
                  maxRows={10}
                  onChange={(event) => setText(event.target.value)}
                />
              </Field>
            )}
            <div className="flex items-center justify-between gap-2">
              <Button variant="ghost" leadingIcon="microphone" onClick={restart}>
                Записать заново
              </Button>
              <Button
                variant="primary"
                leadingIcon={submitIcon}
                disabled={!text.trim() || failed}
                loading={pending}
                onClick={() => onSubmit({ text: text.trim(), durationSec: duration })}
              >
                {submitLabel}
              </Button>
            </div>
          </m.div>
        ) : (
          <m.div
            key="controls"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: softTransition }}
            exit={{ opacity: 0 }}
            className="flex items-center justify-center gap-2"
          >
            {state.status === 'recording' ? (
              <>
                <Button variant="ghost" onClick={recorder.cancel}>
                  Отменить
                </Button>
                <Button variant="primary" leadingIcon="player-stop" onClick={recorder.stop}>
                  Остановить
                </Button>
              </>
            ) : (
              <Button
                variant="primary"
                leadingIcon="microphone"
                loading={state.status === 'requesting' || transcribing}
                onClick={() => void recorder.start()}
              >
                Начать запись
              </Button>
            )}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}
