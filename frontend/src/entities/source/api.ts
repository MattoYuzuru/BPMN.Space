import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { api, errorMessage, postForm, type Schemas, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import type { Sample, Source } from './model'

function useProjectCache(projectId: string) {
  const client = useQueryClient()
  const key = projectKeys.detail(projectId)
  const patch = (update: (project: ProjectDetail) => ProjectDetail) =>
    client.setQueryData<ProjectDetail>(key, (project) => project && update(project))
  const appendSource = (source: Source) =>
    patch((project) => ({
      ...project,
      sources: [...project.sources.filter((item) => item.id !== source.id), source],
    }))
  const invalidate = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: key }),
      client.invalidateQueries({ queryKey: projectKeys.lists() }),
    ])
  return { client, key, patch, appendSource, invalidate }
}

/** Добавить текст или расшифровку голоса (без уведомлений — для составных сценариев). */
export async function addTextSource(projectId: string, body: Schemas['SourceTextCreate']) {
  return unwrap(
    await api.POST('/api/v1/projects/{project_id}/sources/text', {
      params: { path: { project_id: projectId } },
      body,
    }),
  )
}

export interface FileUpload {
  file: File
  title?: string
  onProgress?: (fraction: number) => void
}

/** Загрузить файл с ходом загрузки (без уведомлений — для составных сценариев). */
export function uploadFileSource(projectId: string, { file, title, onProgress }: FileUpload) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  return postForm<Source>(`/api/v1/projects/${projectId}/sources/file`, form, { onProgress })
}

/** Текст или проверенная расшифровка голоса. */
export function useAddTextSource(projectId: string) {
  const cache = useProjectCache(projectId)
  return useMutation({
    mutationFn: (body: Schemas['SourceTextCreate']) => addTextSource(projectId, body),
    onSuccess: (source) => {
      cache.appendSource(source)
      toast.success('Источник добавлен', { description: source.title })
    },
    onError: (error) =>
      toast.error('Источник не добавлен', { description: errorMessage(error), duration: 8000 }),
    onSettled: cache.invalidate,
  })
}

/** Файл с ходом загрузки; .docx/.pdf дальше разбираются в фоне (status=processing → опрос проекта). */
export function useAddFileSource(projectId: string) {
  const cache = useProjectCache(projectId)
  return useMutation({
    mutationFn: (upload: FileUpload) => uploadFileSource(projectId, upload),
    onSuccess: (source) => {
      cache.appendSource(source)
      toast.success('Документ загружен', { description: source.title })
    },
    onError: (error, { file }) =>
      toast.error(`Не удалось загрузить «${file.name}»`, {
        description: errorMessage(error),
        duration: 8000,
      }),
    onSettled: cache.invalidate,
  })
}

/** Ключ учебных материалов: список один на всех и не меняется во время сессии. */
export const sampleKeys = { all: ['samples'] as const }

export const samplesQueryOptions = queryOptions({
  queryKey: sampleKeys.all,
  queryFn: async ({ signal }): Promise<Sample[]> =>
    unwrap(await api.GET('/api/v1/samples', { signal })),
  staleTime: Number.POSITIVE_INFINITY,
})

/** Учебные материалы («Примеры» в меню «Добавить источник»). */
export function useSamples() {
  return useQuery(samplesQueryOptions)
}

/** Добавить учебный материал источником (без уведомлений — для составных сценариев). */
export async function addSampleSource(projectId: string, sampleId: string) {
  return unwrap(
    await api.POST('/api/v1/projects/{project_id}/sources/sample', {
      params: { path: { project_id: projectId } },
      body: { sample_id: sampleId },
    }),
  )
}

/** Материал из «Примеров»: документ разбирается в фоне (processing → ready), голос готов сразу. */
export function useAddSampleSource(projectId: string) {
  const cache = useProjectCache(projectId)
  return useMutation({
    mutationFn: (sampleId: string) => addSampleSource(projectId, sampleId),
    onSuccess: (source) => {
      cache.appendSource(source)
      toast.success('Источник добавлен', { description: source.title })
    },
    onError: (error) =>
      toast.error('Источник не добавлен', { description: errorMessage(error), duration: 8000 }),
    onSettled: cache.invalidate,
  })
}

/**
 * Правка источника: название, текст, участие в прогонах. Оптимистично — переключатель
 * и текст меняются сразу, при ошибке возвращаются.
 */
export function useUpdateSource(projectId: string) {
  const cache = useProjectCache(projectId)
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: string } & Schemas['SourceUpdate']) =>
      unwrap(
        await api.PATCH('/api/v1/sources/{source_id}', {
          params: { path: { source_id: id } },
          body,
        }),
      ),
    onMutate: async ({ id, ...body }) => {
      await cache.client.cancelQueries({ queryKey: cache.key })
      const previous = cache.client.getQueryData<ProjectDetail>(cache.key)
      cache.patch((project) => ({
        ...project,
        sources: project.sources.map((source) =>
          source.id === id
            ? {
                ...source,
                title: body.title ?? source.title,
                content: body.content ?? source.content,
                active: body.active ?? source.active,
              }
            : source,
        ),
      }))
      return { previous }
    },
    onError: (error, _vars, context) => {
      if (context?.previous) cache.client.setQueryData(cache.key, context.previous)
      toast.error('Изменения не сохранены', { description: errorMessage(error) })
    },
    onSettled: cache.invalidate,
  })
}

/** Удаление с откатом при ошибке. */
export function useDeleteSource(projectId: string) {
  const cache = useProjectCache(projectId)
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE('/api/v1/sources/{source_id}', { params: { path: { source_id: id } } }),
      ),
    onMutate: async (id) => {
      await cache.client.cancelQueries({ queryKey: cache.key })
      const previous = cache.client.getQueryData<ProjectDetail>(cache.key)
      cache.patch((project) => ({
        ...project,
        sources: project.sources.filter((source) => source.id !== id),
      }))
      return { previous }
    },
    onError: (error, _id, context) => {
      if (context?.previous) cache.client.setQueryData(cache.key, context.previous)
      toast.error('Источник не удалён', { description: errorMessage(error) })
    },
    onSuccess: () => toast.success('Источник удалён'),
    onSettled: cache.invalidate,
  })
}
