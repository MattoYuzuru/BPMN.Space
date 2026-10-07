import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen } from '@testing-library/react'
import type { Question } from '@/entities/question'
import type { Source } from '@/entities/source'
import { renderUi } from '@/test/render'
import { useWorkspaceUi, type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { SourceSheet } from './source-sheet'

const source: Source = {
  id: 's1',
  project_id: 'p1',
  title: 'Регламент',
  kind: 'text',
  status: 'ready',
  content: 'Инженер проверяет заявку. Диспетчер утверждает решение.',
  active: true,
  created_at: '2026-10-01T10:00:00Z',
}
const question = {
  id: 'q1',
  code: 'Q-1',
  text: 'Кто проверяет заявку?',
  about: { source_id: 's1', quote: 'Инженер проверяет заявку.' },
} as Question

function setup(content = source.content, mark?: string) {
  const close = vi.fn()
  const selectQuestion = vi.fn()
  const focusElements = vi.fn()
  const workspace = {
    project: {
      id: 'p1',
      sources: [{ ...source, content }],
      questions: [
        question,
        {
          ...question,
          id: 'q2',
          code: 'Q-2',
          text: 'Как проверяют?',
          about: { source_id: 's1', quote: 'проверяет заявку' },
        },
      ],
      latest_version: {
        trace: { Task_1: { source_id: 's1', quote: 'Инженер проверяет заявку.' } },
      },
    },
    canEdit: false,
    selectQuestion,
    focusElements,
  } as unknown as WorkspaceApi
  const rendered = renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <WorkspaceContext.Provider value={workspace}>
        <SourceSheet sourceId="s1" mark={mark} onClose={close} />
      </WorkspaceContext.Provider>
    </QueryClientProvider>,
  )
  return { ...rendered, close, selectQuestion, focusElements }
}

afterEach(() => useWorkspaceUi.getState().reset())

it('предлагает все вопросы и элемент для одного фрагмента и открывает выбранный вопрос', async () => {
  const { user, close, selectQuestion } = setup()
  await user.click(screen.getByRole('link', { name: /Связи фрагмента/ }))
  expect(screen.getByRole('dialog', { name: 'Связи фрагмента' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Q-1: Кто проверяет заявку?' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Показать элемент Task_1' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Q-2: Как проверяют?' }))
  expect(close).toHaveBeenCalledOnce()
  expect(selectQuestion).toHaveBeenCalledWith('q2', { focus: true })
  expect(useWorkspaceUi.getState().questionSheet).toBe('q2')
})

it('переходит с фрагмента к элементу схемы', async () => {
  const { user, close, focusElements } = setup()
  await user.click(screen.getByRole('link', { name: /Связи фрагмента/ }))
  await user.click(screen.getByRole('button', { name: 'Показать элемент Task_1' }))
  expect(close).toHaveBeenCalledOnce()
  expect(focusElements).toHaveBeenCalledWith(['Task_1'])
})

it('показывает исходную цитату при изменённом документе без ложного перехода', () => {
  setup('Аналитик согласует договор.', 'Инженер проверяет заявку.')
  expect(screen.getByRole('status')).toHaveTextContent('Цитата не найдена в текущем тексте')
  expect(screen.getByRole('status')).toHaveTextContent('Инженер проверяет заявку.')
  expect(screen.queryByRole('link', { name: /Связи фрагмента/ })).not.toBeInTheDocument()
})

it('подсвечивает выбранную цитату целиком, даже если сохранённый фрагмент короче', () => {
  const mark = 'Инженер проверяет заявку. Диспетчер'
  setup(source.content, mark)
  const target = document.querySelector('[data-testid="source-content"] [data-target="true"]')
  expect(target).toHaveTextContent(mark)
})
