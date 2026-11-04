import {
  type ReactNode,
  type Ref,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'
import { cn } from '@/shared/lib/cn'
import { formatClock } from '@/shared/lib/format'
import { Button } from '../button/button'
import { Icon } from '../icon'
import { IconButton } from '../icon-button/icon-button'
import { Progress } from '../progress/progress'
import { Slider } from '../slider/slider'

export interface MediaPlayerHandle {
  /** Перемотать на секунду и продолжить с неё (реплика, таймкод цитаты). */
  seek: (seconds: number) => void
  play: () => void
  pause: () => void
  currentTime: () => number
}

export interface MediaPlayerProps {
  /** Адрес записи: same-origin, браузер сам делает Range-запросы. */
  src: string
  kind: 'audio' | 'video'
  /** Подпись плеера для скринридера: название записи. */
  label: string
  /** Длительность из источника, пока метаданные не загрузились. */
  durationSec?: number | null
  /** Начальная позиция (таймкод цитаты при открытии листа). */
  initialTime?: number
  onTimeUpdate?: (seconds: number) => void
  onSeek?: (seconds: number) => void
  className?: string
  ref?: Ref<MediaPlayerHandle>
  /** Дополнительная строка под плеером: реплики, пояснения. */
  children?: ReactNode
}

const clamp = (value: number, max: number) => Math.min(Math.max(value, 0), Math.max(max, 0))

/** jsdom и старые браузеры могут не вернуть Promise; играем, не падая на реализации. */
function tryPlay(media: HTMLMediaElement | null, onError: () => void) {
  if (!media) return
  try {
    const result = media.play()
    if (result && typeof result.catch === 'function') {
      void result.catch(() => onError())
    }
  } catch {
    onError()
  }
}

/**
 * Плеер записи: без нативных контролов, управление на дизайн-системе. Браузер запрашивает файл
 * через Range сам; мы показываем загрузку, ошибку и перемотку клавиатурой (Slider).
 */
export function MediaPlayer({
  src,
  kind,
  label,
  durationSec = null,
  initialTime = 0,
  onTimeUpdate,
  onSeek,
  className,
  ref,
  children,
}: MediaPlayerProps) {
  const mediaRef = useRef<HTMLMediaElement>(null)
  const [playing, setPlaying] = useState(false)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [current, setCurrent] = useState(initialTime)
  const [duration, setDuration] = useState(durationSec ?? 0)

  const applyTime = useCallback(
    (seconds: number) => {
      const media = mediaRef.current
      const next = clamp(seconds, duration)
      setCurrent(next)
      if (media) media.currentTime = next
    },
    [duration],
  )

  useImperativeHandle(ref, () => ({
    seek: (seconds) => {
      applyTime(seconds)
      onSeek?.(clamp(seconds, duration))
      tryPlay(mediaRef.current, () => setFailed(true))
    },
    play: () => tryPlay(mediaRef.current, () => setFailed(true)),
    pause: () => mediaRef.current?.pause(),
    currentTime: () => current,
  }))

  // Смена записи — сбрасываем состояние плеера.
  // biome-ignore lint/correctness/useExhaustiveDependencies: источник задаёт начальную позицию
  useEffect(() => {
    setCurrent(initialTime)
    setDuration(durationSec ?? 0)
    setReady(false)
    setFailed(false)
    setPlaying(false)
  }, [src, initialTime, durationSec])

  const toggle = () => {
    const media = mediaRef.current
    if (!media) return
    if (playing) {
      media.pause()
      setPlaying(false)
    } else {
      setPlaying(true)
      tryPlay(media, () => {
        setPlaying(false)
        setFailed(true)
      })
    }
  }

  const retry = () => {
    setFailed(false)
    setReady(false)
    setAttempt((value) => value + 1)
  }

  const mediaProps = {
    src,
    preload: 'metadata' as const,
    onLoadedMetadata: (event: React.SyntheticEvent<HTMLMediaElement>) => {
      const media = event.currentTarget
      setReady(true)
      if (Number.isFinite(media.duration)) setDuration(media.duration)
      if (initialTime > 0) media.currentTime = clamp(initialTime, media.duration)
    },
    onTimeUpdate: (event: React.SyntheticEvent<HTMLMediaElement>) => {
      const seconds = event.currentTarget.currentTime
      setCurrent(seconds)
      onTimeUpdate?.(seconds)
    },
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onEnded: () => setPlaying(false),
    onError: () => setFailed(true),
    'aria-label': label,
    className: cn(
      kind === 'video' ? 'max-h-72 w-full rounded-md border border-border bg-bg-subtle' : 'hidden',
    ),
  }

  return (
    // biome-ignore lint/a11y/useSemanticElements: смысловая группа плеера без формы
    <div
      role="group"
      aria-label={`Плеер: ${label}`}
      data-testid="media-player"
      className={cn('flex w-full flex-col gap-2', className)}
    >
      {kind === 'video' ? (
        <video
          {...mediaProps}
          key={`${src}:${attempt}`}
          ref={mediaRef as unknown as Ref<HTMLVideoElement>}
          playsInline
        />
      ) : (
        <audio
          {...mediaProps}
          key={`${src}:${attempt}`}
          ref={mediaRef as unknown as Ref<HTMLAudioElement>}
        />
      )}

      {failed ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md bg-amber-subtle px-3 py-2.5 type-caption text-amber-fg"
        >
          <Icon name="alert-triangle" size={14} className="mt-0.5 shrink-0" />
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <span>Запись не загрузилась. Файл недоступен, ссылка истекла или нет доступа.</span>
            <span>
              <Button size="sm" variant="ghost" leadingIcon="refresh" onClick={retry}>
                Повторить
              </Button>
            </span>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <IconButton
            icon={playing ? 'player-pause' : 'player-play'}
            size="sm"
            label={playing ? 'Пауза' : 'Слушать'}
            aria-pressed={playing}
            onClick={toggle}
          />
          <span className="type-caption shrink-0 text-fg-muted tabular-nums" data-numeric>
            {formatClock(current)} / {formatClock(duration)}
          </span>
          <Slider
            label="Позиция записи"
            value={clamp(current, duration)}
            max={Math.max(duration, 1)}
            step={1}
            formatValue={formatClock}
            className="min-w-0 flex-1"
            onValueChange={(seconds) => {
              setCurrent(seconds)
              const media = mediaRef.current
              if (media && ready) media.currentTime = seconds
            }}
            onValueCommit={(seconds) => {
              applyTime(seconds)
              onSeek?.(seconds)
            }}
          />
        </div>
      )}
      {!ready && !failed && <Progress label={`Загрузка записи: ${label}`} />}
      {children}
    </div>
  )
}
