import { cn } from '@/shared/lib/cn'
import { formatClock } from '@/shared/lib/format'
import { AudioLevel } from '../audio-level/audio-level'
import { IconButton } from '../icon-button/icon-button'
import { Progress } from '../progress/progress'

export interface VoiceInputProps {
  phase: 'requesting' | 'recording' | 'transcribing'
  levels: readonly number[]
  elapsed: number
  onCancel: () => void
  /** Остановить и вернуть расшифровку в текстовое поле. */
  onStop: () => void
  /** Распознать и сразу отправить. Если не задано, остаётся только остановка. */
  onSend?: () => void
  sendLabel?: string
  className?: string
}

/** Компактная запись вместо текстового поля; расшифровка и черновик принадлежат вызывающей форме. */
export function VoiceInput({
  phase,
  levels,
  elapsed,
  onCancel,
  onStop,
  onSend,
  sendLabel = 'Распознать и отправить',
  className,
}: VoiceInputProps) {
  const recording = phase === 'recording'
  return (
    <div
      className={cn(
        '@container/voice flex min-h-22 min-w-0 flex-col justify-center gap-2 rounded-md border border-accent/45 bg-surface px-2.5 py-2 shadow-xs',
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 px-1">
        <span role="status" className="type-caption text-fg-muted">
          {recording
            ? 'Идёт запись'
            : phase === 'requesting'
              ? 'Подключаю микрофон'
              : 'Распознаю речь'}
        </span>
        <span data-numeric className="type-code text-xs text-fg-subtle" aria-hidden="true">
          {formatClock(elapsed)}
        </span>
      </div>
      <div className="flex min-w-0 items-center gap-1.5">
        <IconButton
          icon="x"
          label="Отменить запись"
          onClick={onCancel}
          className="shrink-0 rounded-full"
        />
        <div className="flex min-w-0 flex-1 flex-col justify-center gap-1">
          <AudioLevel
            levels={levels}
            bars={32}
            active={recording}
            label="Уровень сигнала микрофона"
            className="h-8 w-full gap-0.5 @xs/voice:gap-1"
          />
          {phase === 'transcribing' && <Progress label="Распознавание речи" />}
        </div>
        <IconButton
          icon="player-stop"
          label="Остановить и вставить текст"
          variant="secondary"
          disabled={!recording}
          onClick={onStop}
          className="shrink-0 rounded-full"
        />
        {onSend && (
          <IconButton
            icon="send"
            label={sendLabel}
            variant="primary"
            disabled={!recording}
            onClick={onSend}
            className="shrink-0 rounded-full"
          />
        )}
      </div>
    </div>
  )
}
