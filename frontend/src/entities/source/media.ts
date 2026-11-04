/**
 * Медиа волны 3: плеер пишет/читает запись через `GET /sources/{id}/media`, реплики — через
 * `GET /sources/{id}/segments`, оценка профиля записи — POST до загрузки, повтор OCR — POST.
 * Всё — same-origin с cookies; Range-запросы делает сам браузер.
 */
import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectKeys } from '@/entities/project'
import { api, errorMessage, type Schemas, unwrap } from '@/shared/api/client'
import type { IconName } from '@/shared/ui'
import { toast } from '@/shared/ui'

export type MediaSegment = Schemas['MediaSegment']
export type SourceSegments = Schemas['SourceSegments']
export type MediaEstimate = Schemas['MediaEstimate']
export type MediaEstimateRequest = Schemas['MediaEstimateRequest']
export type MediaProfile = Schemas['MediaProfile']

/** Профили обработки записи (RFC-0006, волна 3): чем подробнее кадры, тем дороже. */
export const MEDIA_PROFILES: {
  value: MediaProfile
  label: string
  description: string
  icon: IconName
}[] = [
  {
    value: 'audio',
    label: 'Только звук',
    description: 'Расшифровка речи с таймкодами, без кадров.',
    icon: 'transcript',
  },
  {
    value: 'sparse',
    label: 'Звук + редкие кадры',
    description: 'Расшифровка и несколько ключевых кадров экрана.',
    icon: 'photo',
  },
  {
    value: 'detailed',
    label: 'Подробно',
    description: 'Частые кадры и описание экрана — дороже, но видны все шаги.',
    icon: 'video',
  },
]

export const DEFAULT_MEDIA_PROFILE: MediaProfile = 'sparse'

export function mediaProfileLabel(profile: MediaProfile | string): string {
  return MEDIA_PROFILES.find((item) => item.value === profile)?.label ?? 'Обработка записи'
}

export function isMediaProfile(value: unknown): value is MediaProfile {
  return MEDIA_PROFILES.some((item) => item.value === value)
}

/** Адрес медиа: same-origin, относительный — браузер сам добавит cookies и Range. */
export function sourceMediaUrl(sourceId: string): string {
  return `/api/v1/sources/${sourceId}/media`
}

export const sourceMediaKeys = {
  segments: (sourceId: string) => ['source', sourceId, 'segments'] as const,
}

export function sourceSegmentsQueryOptions(sourceId: string) {
  return queryOptions({
    queryKey: sourceMediaKeys.segments(sourceId),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/sources/{source_id}/segments', {
          params: { path: { source_id: sourceId } },
          signal,
        }),
      ),
    staleTime: 60_000,
    retry: false,
  })
}

/** Реплики расшифровки: таймкоды для перемотки. Недоступны — плеер работает без списка. */
export function useSourceSegments(sourceId: string | null | undefined) {
  return useQuery({ ...sourceSegmentsQueryOptions(sourceId ?? ''), enabled: Boolean(sourceId) })
}

/** Оценка обработки записи до загрузки: минуты STT, кадры, диапазон стоимости. */
export function useMediaEstimate(projectId: string) {
  return useMutation({
    mutationFn: async (body: MediaEstimateRequest) =>
      unwrap(
        await api.POST('/api/v1/projects/{project_id}/sources/media/estimate', {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
  })
}

/**
 * Повторить OCR страниц-сканов PDF: сервер создаёт/перезапускает производный узел OCR,
 * готовые страницы не распознаёт заново. Прогресс виден по статусу производного узла.
 */
export function useRetrySourceOcr(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (sourceId: string) =>
      unwrap(
        await api.POST('/api/v1/sources/{source_id}/ocr', {
          params: { path: { source_id: sourceId } },
        }),
      ),
    onSuccess: () => {
      toast.success('Распознавание запущено', {
        description: 'Готовые страницы сохранятся: прогресс виден в листе источника и дереве.',
      })
      return client.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
    },
    onError: (error) =>
      toast.error('Не удалось запустить распознавание', {
        description: errorMessage(error),
        duration: 8000,
      }),
  })
}
