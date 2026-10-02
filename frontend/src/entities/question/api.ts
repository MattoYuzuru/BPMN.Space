import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { api, errorMessage, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import { type Question, type QuestionStatus, shiftSummary } from './model'

/** Заменить вопрос в кэше проекта (и сдвинуть сводку). Используется мутациями и событиями SSE. */
export function upsertQuestion(client: QueryClient, projectId: string, question: Question) {
  client.setQueryData<ProjectDetail>(projectKeys.detail(projectId), (project) => {
    if (!project) return project
    const index = project.questions.findIndex((item) => item.id === question.id)
    if (index === -1) return { ...project, questions: [...project.questions, question] }
    const previous = project.questions[index] as Question
    const questions = project.questions.slice()
    questions[index] = question
    return {
      ...project,
      questions,
      summary: shiftSummary(project.summary, previous.status, question.status),
    }
  })
}

type Action = { type: 'answer'; text: string } | { type: 'ignore' } | { type: 'reopen' }

const TARGET: Record<Action['type'], QuestionStatus> = {
  answer: 'answered',
  ignore: 'ignored',
  reopen: 'open',
}

const FAILURE: Record<Action['type'], string> = {
  answer: 'Ответ не сохранён',
  ignore: 'Не удалось принять допущение',
  reopen: 'Не удалось вернуть вопрос',
}

async function send(question: Question, action: Action): Promise<Question> {
  const path = { params: { path: { question_id: question.id } } }
  switch (action.type) {
    case 'answer':
      return unwrap(
        await api.POST('/api/v1/questions/{question_id}/answer', {
          ...path,
          body: { text: action.text },
        }),
      )
    case 'ignore':
      return unwrap(await api.POST('/api/v1/questions/{question_id}/ignore', path))
    case 'reopen':
      return unwrap(await api.POST('/api/v1/questions/{question_id}/reopen', path))
  }
}

/**
 * Действия с вопросом с оптимистичным обновлением: карточка переходит в новый статус сразу,
 * при ошибке возвращается, а пользователь видит toast с возможностью повторить.
 */
export function useQuestionAction(projectId: string) {
  const client = useQueryClient()
  const key = projectKeys.detail(projectId)
  const mutation = useMutation({
    mutationFn: ({ question, action }: { question: Question; action: Action }) =>
      send(question, action),
    onMutate: async ({ question, action }) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<ProjectDetail>(key)
      upsertQuestion(client, projectId, {
        ...question,
        status: TARGET[action.type],
        answer: action.type === 'answer' ? { source_id: '', text: action.text } : question.answer,
        updated_at: new Date().toISOString(),
      })
      return { previous }
    },
    onError: (error, variables, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
      toast.error(FAILURE[variables.action.type], {
        description: errorMessage(error),
        action: { label: 'Повторить', onClick: () => mutation.mutate(variables) },
        duration: 8000,
      })
    },
    onSuccess: (question) => upsertQuestion(client, projectId, question),
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  })
  return mutation
}
