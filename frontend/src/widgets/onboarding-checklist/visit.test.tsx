import { act, renderHook, waitFor } from '@testing-library/react'
import { useOnboardingUi } from '@/entities/onboarding'
import { TOUR_ANCHORS } from '@/shared/lib/tour-anchors'
import { stubApi } from '@/test/api-stub'
import { registerWorkspaceControls } from '@/widgets/workspace/model'
import { useVisitItem } from './visit'

const navigate = vi.fn(async () => {})
vi.mock('@tanstack/react-router', async (original) => ({
  ...(await original<typeof import('@tanstack/react-router')>()),
  useNavigate: () => navigate,
}))

const showHint = vi.fn()
vi.mock('@/features/onboarding/hint', () => ({
  showHint: (request: unknown) => showHint(request),
  hideHint: vi.fn(),
}))

const toastError = vi.fn()
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: (...args: unknown[]) => toastError(...args) }),
}))

const target = (item: string) => `GET /api/v1/me/onboarding/items/${item}/target`

afterEach(() => {
  vi.unstubAllGlobals()
  navigate.mockClear()
  showHint.mockClear()
  toastError.mockClear()
  act(() => useOnboardingUi.getState().closeChecklist())
})

describe('переход к пункту чек-листа', () => {
  it('запрашивает target, закрывает панель, переходит с ?question= и показывает подсказку', async () => {
    const calls = stubApi({
      [target('question_answered')]: {
        body: { route: 'workspace', project_id: 'p1', question_id: 'q1', hint: 'do_item' },
      },
    })
    const controls = { expandPanel: vi.fn(), selectQuestion: vi.fn() }
    const unregister = registerWorkspaceControls(controls)
    act(() => useOnboardingUi.getState().openChecklist())
    const { result } = renderHook(() => useVisitItem())

    await act(() => result.current.visit('question_answered'))

    expect(calls.map((call) => call.path)).toContain(
      '/api/v1/me/onboarding/items/question_answered/target',
    )
    expect(useOnboardingUi.getState().checklistOpen).toBe(false)
    expect(navigate).toHaveBeenCalledWith({
      to: '/projects/$projectId',
      params: { projectId: 'p1' },
      search: { question: 'q1' },
    })
    expect(showHint).toHaveBeenCalledOnce()
    const request = showHint.mock.calls[0]?.[0] as {
      anchor: unknown
      text: string
      prepare: () => void
    }
    expect(request.anchor).toEqual({
      name: TOUR_ANCHORS.questionAnswer,
      within: '[data-question-id="q1"]',
    })
    expect(request.text).toBe('Нажмите «Ответить» и напишите ответ — он станет новым источником.')

    // prepare: раскрыть панель вопросов и выбрать вопрос с показом на схеме
    request.prepare()
    await waitFor(() => expect(controls.selectQuestion).toHaveBeenCalledWith('q1', { focus: true }))
    expect(controls.expandPanel).toHaveBeenCalledWith('questions')
    unregister()
  })

  it('экран проектов: переход на «/» и подсказка на «Новый проект»', async () => {
    stubApi({ [target('project_created')]: { body: { route: 'projects', hint: 'do_item' } } })
    const { result } = renderHook(() => useVisitItem())
    await act(() => result.current.visit('project_created'))
    expect(navigate).toHaveBeenCalledWith({ to: '/' })
    expect(showHint.mock.calls[0]?.[0]).toMatchObject({ anchor: TOUR_ANCHORS.projectsNew })
  })

  it('«Сначала…»: текст подготовительного шага', async () => {
    stubApi({
      [target('diagram_edited')]: {
        body: { route: 'workspace', project_id: 'p1', hint: 'need_diagram' },
      },
    })
    const { result } = renderHook(() => useVisitItem())
    await act(() => result.current.visit('diagram_edited'))
    expect(showHint.mock.calls[0]?.[0]).toMatchObject({
      text: 'Сначала постройте схему.',
      anchor: TOUR_ANCHORS.runBuild,
    })
  })

  it('ошибка запроса — уведомление, панель остаётся, перехода нет', async () => {
    stubApi({ [target('project_shared')]: { status: 500, body: { detail: 'Сбой' } } })
    act(() => useOnboardingUi.getState().openChecklist())
    const { result } = renderHook(() => useVisitItem())
    await act(() => result.current.visit('project_shared'))
    expect(toastError).toHaveBeenCalledOnce()
    expect(useOnboardingUi.getState().checklistOpen).toBe(true)
    expect(navigate).not.toHaveBeenCalled()
    expect(showHint).not.toHaveBeenCalled()
    expect(result.current.pending).toBeNull()
  })
})
