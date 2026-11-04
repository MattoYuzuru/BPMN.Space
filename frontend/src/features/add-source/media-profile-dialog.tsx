import { useEffect, useState } from 'react'
import {
  MEDIA_PROFILES,
  type MediaEstimate,
  type MediaProfile,
  useMediaEstimate,
} from '@/entities/source'
import { cn } from '@/shared/lib/cn'
import { formatMoneyRange, formatNumber } from '@/shared/lib/format'
import { Button, Card, Dialog, DialogContent, Icon, Skeleton } from '@/shared/ui'
import { mediaFileInfo } from './media-duration'

export interface MediaProfileChoice {
  profile: MediaProfile
}

/**
 * Профиль обработки записи до загрузки: «Только звук / редкие кадры / подробно» с оценкой
 * минут распознавания, кадров и цены. Предупреждаем, что запись уходит провайдеру.
 */
export function MediaProfileDialog({
  projectId,
  files,
  onCancel,
  onConfirm,
}: {
  projectId: string
  files: File[]
  onCancel: () => void
  onConfirm: (profile: MediaProfile) => void
}) {
  const [profile, setProfile] = useState<MediaProfile>('sparse')
  const estimate = useMediaEstimate(projectId)
  const [infos, setInfos] = useState<{ file: File; durationSec: number; hasVideo: boolean }[]>([])
  const [estimates, setEstimates] = useState<(MediaEstimate | null)[]>([])
  const [estimating, setEstimating] = useState(false)

  // Длительность читается в браузере по метаданным; оценка — после этого.
  useEffect(() => {
    let cancelled = false
    setEstimating(true)
    void Promise.all(files.map((file) => mediaFileInfo(file).then((info) => ({ file, ...info }))))
      .then(async (loaded) => {
        if (cancelled) return
        setInfos(loaded)
        const results = await Promise.all(
          loaded.map((info) =>
            estimate
              .mutateAsync({
                duration_sec: Math.max(1, Math.round(info.durationSec)),
                has_video: info.hasVideo,
                media_profile: profile,
              })
              .catch(() => null),
          ),
        )
        if (!cancelled) setEstimates(results)
      })
      .finally(() => {
        if (!cancelled) setEstimating(false)
      })
    return () => {
      cancelled = true
    }
  }, [files, profile, estimate.mutateAsync])

  const total = estimates.reduce(
    (sum, item) => (item ? sum + (item.total_cost_usd.min_usd ?? 0) : sum),
    0,
  )
  const totalMax = estimates.reduce(
    (sum, item) => (item ? sum + (item.total_cost_usd.max_usd ?? 0) : sum),
    0,
  )
  return (
    <Dialog open onOpenChange={(next) => !next && onCancel()}>
      <DialogContent
        title="Как обработать запись"
        description="Запись распознаётся провайдером: расшифровка с таймкодами и, если выбрано, кадры экрана."
        footer={
          <>
            <Button variant="ghost" onClick={onCancel}>
              Отмена
            </Button>
            <Button variant="primary" leadingIcon="upload" onClick={() => onConfirm(profile)}>
              Загрузить {formatNumber(files.length)} {files.length === 1 ? 'файл' : 'файлов'}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            {MEDIA_PROFILES.map((item) => (
              <Button
                key={item.value}
                variant="ghost"
                aria-pressed={profile === item.value}
                onClick={() => setProfile(item.value)}
                className={cn(
                  'h-auto w-full items-start justify-start gap-3 border py-2 text-left',
                  profile === item.value
                    ? 'border-accent/50 bg-surface'
                    : 'border-border bg-transparent',
                )}
              >
                <Icon name={item.icon} size={20} className="mt-0.5 shrink-0 text-fg-muted" />
                <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
                  <span className="type-ui font-medium text-fg">{item.label}</span>
                  <span className="type-caption font-normal whitespace-normal text-fg-muted">
                    {item.description}
                  </span>
                </span>
                {profile === item.value && (
                  <Icon name="circle-check" size={16} className="text-accent" />
                )}
              </Button>
            ))}
          </div>

          <div className="flex flex-col gap-2">
            <span className="type-label text-fg-muted">Оценка</span>
            {estimating && <Skeleton className="h-12 w-full" />}
            {!estimating &&
              infos.map((info, index) => {
                const item = estimates[index]
                return (
                  <div key={info.file.name} className="flex flex-wrap items-baseline gap-x-3">
                    <span className="min-w-0 flex-1 truncate type-caption text-fg">
                      {info.file.name}
                    </span>
                    {item ? (
                      <span className="type-caption text-fg-muted" data-numeric>
                        {item.stt.minutes > 0 &&
                          `${formatNumber(Math.ceil(item.stt.minutes))} мин речи \u00B7 `}
                        {item.frames.count_max > 0 &&
                          `${formatNumber(item.frames.count_max)} кадров \u00B7 `}
                        {formatMoneyRange(
                          item.total_cost_usd.min_usd ?? 0,
                          item.total_cost_usd.max_usd ?? 0,
                          item.currency,
                        )}
                      </span>
                    ) : (
                      <span className="type-caption text-fg-subtle">Оценка недоступна</span>
                    )}
                  </div>
                )
              })}
            {!estimating && estimates.some(Boolean) && (
              <span className="type-caption text-fg-muted" data-numeric>
                Итого: {formatMoneyRange(total, totalMax)}
                {estimates[0]?.note ? ` \u00B7 ${estimates[0].note}` : ''}
              </span>
            )}
          </div>

          <Card variant="sunken" padding="sm" className="flex items-start gap-2">
            <Icon name="shield-check" size={16} className="mt-0.5 shrink-0 text-fg-subtle" />
            <p className="type-caption text-fg-muted">
              Запись уходит выбранному провайдеру и может обрабатываться за пределами РФ. Не
              загружайте материалы, которые нельзя передавать внешним сервисам.
            </p>
          </Card>
        </div>
      </DialogContent>
    </Dialog>
  )
}
