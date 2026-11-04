import { screen } from '@testing-library/react'
import { renderUi } from '@/test/render'
import { Badge } from '../badge/badge'
import { type TreeItem, TreeView } from './tree-view'

const ITEMS: TreeItem[] = [
  {
    id: 'recording',
    label: 'встреча.mp4',
    icon: 'audio',
    children: [
      {
        id: 'transcript',
        label: 'Расшифровка: встреча.mp4',
        icon: 'transcript',
        meta: <Badge tone="accent">ИИ</Badge>,
      },
      {
        id: 'frames',
        label: 'Ключевые кадры',
        icon: 'photo',
        children: [{ id: 'frame-1', label: 'Описание экрана', icon: 'photo' }],
      },
    ],
  },
  { id: 'rules', label: 'Регламент ТП.docx', icon: 'file-description' },
]

const item = (name: string | RegExp) => screen.getByRole('treeitem', { name })

describe('TreeView', () => {
  it('это дерево: уровни, раскрытие и дополнительная метка в строке', () => {
    renderUi(<TreeView label="Материалы" items={ITEMS} />)
    expect(screen.getByRole('tree', { name: 'Материалы' })).toBeInTheDocument()
    expect(screen.getAllByRole('treeitem')).toHaveLength(5)
    expect(item('встреча.mp4')).toHaveAttribute('aria-level', '1')
    expect(item('встреча.mp4')).toHaveAttribute('aria-expanded', 'true')
    expect(item(/Расшифровка/)).toHaveAttribute('aria-level', '2')
    expect(item(/Описание экрана/)).toHaveAttribute('aria-level', '3')
    expect(item(/Регламент/)).not.toHaveAttribute('aria-expanded')
    expect(screen.getByText('ИИ')).toBeInTheDocument()
  })

  it('стрелки идут по видимым строкам, раскрывают и сворачивают ветки', async () => {
    const { user } = renderUi(<TreeView label="Материалы" items={ITEMS} />)
    item('встреча.mp4').focus()
    await user.keyboard('{ArrowDown}')
    expect(document.activeElement).toBe(item(/Расшифровка/))
    await user.keyboard('{ArrowDown}')
    expect(document.activeElement).toBe(item(/Ключевые кадры/))
    await user.keyboard('{ArrowRight}')
    expect(document.activeElement).toBe(item(/Описание экрана/))
    await user.keyboard('{ArrowLeft}')
    expect(document.activeElement).toBe(item(/Ключевые кадры/))
    await user.keyboard('{ArrowLeft}')
    expect(item(/Ключевые кадры/)).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('treeitem', { name: /Описание экрана/ })).toBeNull()
    await user.keyboard('{ArrowUp}')
    expect(document.activeElement).toBe(item(/Расшифровка/))
    await user.keyboard('{End}')
    expect(document.activeElement).toBe(item(/Регламент/))
    await user.keyboard('{Home}')
    expect(document.activeElement).toBe(item('встреча.mp4'))
  })

  it('клик выбирает узел, клик по стрелке раскрывает', async () => {
    const onSelect = vi.fn()
    const { user } = renderUi(
      <TreeView
        label="Материалы"
        items={ITEMS}
        defaultExpandedIds={['recording']}
        onSelect={onSelect}
      />,
    )
    await user.click(item(/Расшифровка/))
    expect(onSelect).toHaveBeenCalledWith('transcript')
    const chevron = item(/Ключевые кадры/).querySelector('[data-part="chevron"]')
    expect(chevron).not.toBeNull()
    await user.click(chevron as Element)
    expect(item(/Ключевые кадры/)).toHaveAttribute('aria-expanded', 'true')
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('Enter выбирает и раскрывает ветку', async () => {
    const onSelect = vi.fn()
    const { user } = renderUi(
      <TreeView label="Материалы" items={ITEMS} onSelect={onSelect} defaultExpandedIds={[]} />,
    )
    item('встреча.mp4').focus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith('recording')
    expect(item('встреча.mp4')).toHaveAttribute('aria-expanded', 'true')
  })

  it('пустое дерево показывает спокойный текст', () => {
    renderUi(<TreeView label="Материалы" items={[]} emptyLabel="Материалов пока нет" />)
    expect(screen.getByText('Материалов пока нет')).toBeInTheDocument()
    expect(screen.queryByRole('tree')).toBeNull()
  })
})
