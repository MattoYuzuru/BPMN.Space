import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createProject, projectKeys, projectQueryOptions } from '@/entities/project'
import { startRun } from '@/entities/run'
import { addTextSource, uploadFileSource } from '@/entities/source'
import { type CreateFlowInput, runCreateFlow } from './create-flow'

/**
 * Создание проекта с описанием и файлами одним действием (см. `runCreateFlow`). Вызывать через
 * `mutateAsync`: колбэки `mutate` теряются, если диалог закрыли и компонент размонтирован.
 */
export function useCreateProjectFlow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateFlowInput) =>
      runCreateFlow(input, {
        createProject,
        addText: addTextSource,
        uploadFile: (projectId, file) => uploadFileSource(projectId, { file }),
        startBuild: (projectId) => startRun(projectId, 'build'),
        fetchProject: (projectId) =>
          client.fetchQuery({ ...projectQueryOptions(projectId), staleTime: 0 }),
      }),
    onSettled: () => client.invalidateQueries({ queryKey: projectKeys.lists() }),
  })
}
