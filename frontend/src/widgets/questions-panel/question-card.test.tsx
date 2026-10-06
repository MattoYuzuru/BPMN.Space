import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import type { Question } from '@/entities/question'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { QuestionCard } from './question-card'

const question: Question = {
  id: 'q1',
  project_id: 'p1',
  code: 'Q-1',
  kind: 'missing_actor',
  severity: 'blocker',
  status: 'answered',
  text: 'Кто готовит акт?',
  assumption: 'Акт готовит бухгалтер.',
  element_ids: [],
  answer: { source_id: 'answer-source', text: 'Акт готовит инженер.' },
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
}

afterEach(() => vi.unstubAllGlobals())

it('отвеченный вопрос честно показывает ожидание анализа и сохраняет возврат', async () => {
  const calls = stubApi({
    'POST /api/v1/questions/q1/reopen': { body: { ...question, status: 'open', answer: null } },
  })
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  const workspace = {
    project: { id: 'p1', sources: [] },
    canEdit: true,
    selectQuestion: vi.fn(),
    focusElements: vi.fn(),
  } as unknown as WorkspaceApi
  const { user } = renderUi(
    <QueryClientProvider client={client}>
      <WorkspaceContext.Provider value={workspace}>
        <QuestionCard question={question} />
      </WorkspaceContext.Provider>
    </QueryClientProvider>,
  )
  expect(screen.getByText('Ответ получен')).toBeVisible()
  expect(screen.getByText('Ответ учтётся при следующем анализе')).toBeVisible()
  expect(screen.getByText('Акт готовит инженер.')).toBeVisible()
  expect(screen.queryByText('Решён', { exact: true })).not.toBeInTheDocument()
  expect(screen.queryByText('Блокирует')).not.toBeInTheDocument()
  expect(screen.queryByText('Акт готовит бухгалтер.')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Вернуть' }))
  await waitFor(() =>
    expect(calls.some((call) => call.path === '/api/v1/questions/q1/reopen')).toBe(true),
  )
})
