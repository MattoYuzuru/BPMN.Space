import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  type Source,
  sourceMediaKeys,
  sourceMediaUrl,
  sourcePlayback,
  useSourceSegments,
} from '@/entities/source'
import { formatClock, formatCount } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  Card,
  Icon,
  MediaPlayer,
  type MediaPlayerHandle,
  ScrollArea,
  Skeleton,
} from '@/shared/ui'

/**
 * Плеер записи в листе источника (волна 3): звук/видео, перемотка по таймкоду и список реплик.
 * Работает и для записи, и для её расшифровки/производных узлов — играет корневую запись.
 */
export function SourceMedia({
  source,
  sources,
  playerRef,
  initialTime = 0,
  onTimeUpdate,
}: {
  source: Source
  sources: readonly Source[]
  playerRef: React.RefObject<MediaPlayerHandle | null>
  initialTime?: number
  onTimeUpdate?: (seconds: number) => void
}) {
  const playback = useMemo(() => sourcePlayback(sources, source), [sources, source])
  const segments = useSourceSegments(playback?.segmentsSourceId)
  const client = useQueryClient()
  const listRef = useRef<HTMLDivElement>(null)
  const [current, setCurrent] = useState(initialTime)
  // Расшифровка доготовилась, пока лист открыт: перечитываем реплики, иначе остался бы 404-кеш.
  const statusRef = useRef(source.status)
  useEffect(() => {
    const wasReady = statusRef.current === 'ready'
    statusRef.current = source.status
    if (!playback || wasReady || source.status !== 'ready') return
    void client.invalidateQueries({
      queryKey: sourceMediaKeys.segments(playback.segmentsSourceId),
    })
  }, [source.status, playback, client])
  const media = playback?.mediaSource ?? null
  const duration = media?.duration_sec ?? segments.data?.duration_sec ?? 0
  const items = segments.data?.segments ?? []
  const activeIndex = items.findIndex(
    (segment) => current >= segment.start_sec && current < segment.end_sec,
  )
  // Активная реплика не должна уезжать за пределы списка при перемотке плеером.
  useEffect(() => {
    if (activeIndex < 0) return
    const active = listRef.current?.querySelector('[aria-current="true"]')
    if (active && 'scrollIntoView' in active && typeof active.scrollIntoView === 'function') {
      active.scrollIntoView({ block: 'nearest' })
    }
  }, [activeIndex])
  if (!playback || !media) return null
  return (
    <Card
      variant="sunken"
      padding="sm"
      className="flex flex-col gap-2"
      data-testid="source-media"
      {...tourAnchor(TOUR_ANCHORS.sourcePlayer)}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {media.media?.has_audio !== null && media.media?.has_audio !== undefined && (
          <Badge
            tone={media.media.has_audio ? 'success' : 'amber'}
            variant="outline"
            icon="wave-sine"
          >
            {media.media.has_audio ? 'Есть звук' : 'Нет звука'}
          </Badge>
        )}
        {playback.hasVideo && (
          <Badge tone="neutral" variant="outline" icon="video">
            Есть видео
          </Badge>
        )}
        {items.length > 0 && (
          <span className="type-caption text-fg-subtle" data-numeric>
            {formatCount(items.length, ['реплика', 'реплики', 'реплик'])}
          </span>
        )}
      </div>
      <MediaPlayer
        ref={playerRef}
        src={sourceMediaUrl(media.id)}
        kind={playback.hasVideo ? 'video' : 'audio'}
        label={media.title}
        durationSec={duration}
        initialTime={initialTime}
        onTimeUpdate={(seconds) => {
          setCurrent(seconds)
          onTimeUpdate?.(seconds)
        }}
        onSeek={(seconds) => onTimeUpdate?.(seconds)}
      />
      {segments.isPending && <Skeleton className="h-4 w-2/3" />}
      {segments.isError && (
        <p className="flex items-center gap-1 type-caption text-fg-subtle">
          <Icon name="alert-circle" size={14} />
          Реплики недоступны — перемотка по таймкодам в тексте работает.
        </p>
      )}
      {items.length > 0 && (
        <ScrollArea className="max-h-48" viewportRef={listRef}>
          <ol aria-label="Реплики записи" className="flex flex-col gap-0.5 pr-1">
            {items.map((segment, index) => {
              const active = index === activeIndex
              return (
                // biome-ignore lint/suspicious/noArrayIndexKey: у реплик бывают одинаковые таймкоды
                <li key={`${segment.start_sec}:${index}`}>
                  <Button
                    variant={active ? 'secondary' : 'ghost'}
                    size="sm"
                    aria-current={active ? 'true' : undefined}
                    className="h-auto w-full justify-start gap-2 py-1 whitespace-normal text-left"
                    onClick={() => playerRef.current?.seek(segment.start_sec)}
                  >
                    <span className="shrink-0 font-mono type-caption text-fg-subtle" data-numeric>
                      {formatClock(segment.start_sec)}
                    </span>
                    {segment.speaker && (
                      <span className="shrink-0 type-caption font-medium text-fg-muted">
                        {segment.speaker}
                      </span>
                    )}
                    <span className="type-caption text-fg">{segment.text}</span>
                  </Button>
                </li>
              )
            })}
          </ol>
        </ScrollArea>
      )}
    </Card>
  )
}
