import { beforeEach, describe, expect, it } from 'vitest'
import { useWorkspaceUi } from './model'

beforeEach(() => useWorkspaceUi.getState().reset())

describe('useWorkspaceUi: точки расширения для обучения', () => {
  it('expandPanel каждый раз создаёт новую просьбу, даже для той же панели', () => {
    const { expandPanel } = useWorkspaceUi.getState()
    expandPanel('sources')
    const first = useWorkspaceUi.getState().expandRequest
    expandPanel('sources')
    const second = useWorkspaceUi.getState().expandRequest
    expect(first).toMatchObject({ panel: 'sources' })
    expect(second).toMatchObject({ panel: 'sources' })
    expect(second?.id).toBeGreaterThan(first?.id ?? 0)
    expandPanel('questions')
    expect(useWorkspaceUi.getState().expandRequest?.panel).toBe('questions')
  })

  it('showQuestionsTab тоже каждый раз новая просьба', () => {
    const { showQuestionsTab } = useWorkspaceUi.getState()
    showQuestionsTab('open')
    const first = useWorkspaceUi.getState().questionsTabRequest
    showQuestionsTab('open')
    expect(useWorkspaceUi.getState().questionsTabRequest?.id).toBeGreaterThan(first?.id ?? 0)
  })

  it('подсказка для текстового диалога ставится и снимается', () => {
    useWorkspaceUi.getState().setTextSuggestion('Опишите процесс')
    expect(useWorkspaceUi.getState().textSuggestion).toBe('Опишите процесс')
    useWorkspaceUi.getState().setTextSuggestion(null)
    expect(useWorkspaceUi.getState().textSuggestion).toBeNull()
  })

  it('выход с экрана сбрасывает просьбу развернуть панель', () => {
    useWorkspaceUi.getState().expandPanel('sources')
    useWorkspaceUi.getState().reset()
    expect(useWorkspaceUi.getState().expandRequest).toBeNull()
  })
})
