import { screen } from '@testing-library/react'
import { CHECKLIST_ITEMS, type ChecklistItemKey } from '@/entities/onboarding'
import { renderUi } from '@/test/render'
import { ChecklistBody } from './checklist-panel'

const doneKeys = (...keys: ChecklistItemKey[]) => new Set(keys)

describe('панель «Начало работы»', () => {
  it('четыре группы и двенадцать пунктов, счётчик «5 из 12»', () => {
    renderUi(
      <ChecklistBody
        doneKeys={doneKeys(
          'project_created',
          'text_source_added',
          'document_uploaded',
          'voice_added',
          'diagram_built',
        )}
        onVisit={() => {}}
        recentAt={{}}
      />,
    )
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      'Источники',
      'Анализ',
      'Схема',
      'Команда',
    ])
    expect(screen.getAllByRole('listitem')).toHaveLength(12)
    expect(screen.getByText('5 из 12')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Выполнено 5 из 12' })).toBeInTheDocument()
  })

  it('невыполненный пункт — кнопка, клик зовёт переход; выполненный не кликабелен', async () => {
    const onVisit = vi.fn()
    const { user } = renderUi(
      <ChecklistBody doneKeys={doneKeys('project_created')} onVisit={onVisit} recentAt={{}} />,
    )
    expect(screen.queryByRole('button', { name: /Создать проект/ })).not.toBeInTheDocument()
    expect(screen.getByText('Создать проект').closest('li')).toHaveTextContent('выполнено')
    // Руками отметить нельзя: ни флажков, ни переключателей.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Ответить на вопрос/ }))
    expect(onVisit).toHaveBeenCalledWith('question_answered')
    await user.click(screen.getByRole('button', { name: /Поделиться проектом/ }))
    expect(onVisit).toHaveBeenLastCalledWith('project_shared')
  })

  it('все двенадцать невыполненных пунктов кликабельны и отдают свой ключ', async () => {
    const onVisit = vi.fn()
    const { user } = renderUi(
      <ChecklistBody doneKeys={doneKeys()} onVisit={onVisit} recentAt={{}} />,
    )
    for (const item of CHECKLIST_ITEMS) {
      await user.click(screen.getByRole('button', { name: new RegExp(item.title) }))
    }
    expect(onVisit.mock.calls.map(([key]) => key)).toEqual(CHECKLIST_ITEMS.map((i) => i.key))
  })

  it('во время тура клики недоступны и есть подпись', async () => {
    const onVisit = vi.fn()
    const { user } = renderUi(
      <ChecklistBody doneKeys={doneKeys()} locked onVisit={onVisit} recentAt={{}} />,
    )
    expect(screen.getByText('Доступно после обучения')).toBeInTheDocument()
    const row = screen.getByRole('button', { name: /Создать проект/ })
    expect(row).toBeDisabled()
    await user.click(row)
    expect(onVisit).not.toHaveBeenCalled()
  })

  it('пока идёт запрос «куда вести», остальные клики игнорируются', async () => {
    const onVisit = vi.fn()
    const { user } = renderUi(
      <ChecklistBody
        doneKeys={doneKeys()}
        pending="project_created"
        onVisit={onVisit}
        recentAt={{}}
      />,
    )
    await user.click(screen.getByRole('button', { name: /Добавить текст/ }))
    expect(onVisit).not.toHaveBeenCalled()
  })

  it('все двенадцать — «Все шаги выполнены», строки без кнопок', () => {
    renderUi(
      <ChecklistBody
        doneKeys={doneKeys(...CHECKLIST_ITEMS.map((i) => i.key))}
        onVisit={() => {}}
        recentAt={{}}
      />,
    )
    expect(screen.getByText('Все шаги выполнены')).toBeInTheDocument()
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })

  it('только что отмеченный пункт при открытии сначала пуст и отмечается на следующем кадре', async () => {
    renderUi(
      <ChecklistBody
        doneKeys={doneKeys('project_shared')}
        onVisit={() => {}}
        recentAt={{ project_shared: Date.now() }}
      />,
    )
    const mark = () =>
      screen.getByText('Поделиться проектом').closest('li')?.querySelector('[data-done]')
    expect(mark()).toBeNull()
    await vi.waitFor(() => expect(mark()).not.toBeNull())
  })
})
