import { fireEvent, screen } from '@testing-library/react'
import { renderUi } from '@/test/render'
import { AudioLevel } from '../audio-level/audio-level'
import { FileDrop } from './file-drop'

const file = (name: string) => new File(['текст'], name, { type: 'text/plain' })

describe('FileDrop', () => {
  it('принимает файл, выбранный кнопкой', async () => {
    const onFiles = vi.fn()
    const { user, container } = renderUi(
      <FileDrop accept=".md" onFiles={onFiles} title="Перетащите документ" />,
    )
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, file('a.md'))
    expect(onFiles).toHaveBeenCalledWith([expect.objectContaining({ name: 'a.md' })])
    expect(screen.getByRole('button', { name: 'Выбрать файл' })).toBeEnabled()
  })

  it('подсвечивается при перетаскивании и отдаёт сброшенные файлы', () => {
    const onFiles = vi.fn()
    const { container } = renderUi(
      <FileDrop accept=".md" multiple onFiles={onFiles} title="Перетащите документ" />,
    )
    const zone = container.firstElementChild as HTMLElement
    const dataTransfer = { types: ['Files'], files: [file('a.md'), file('b.md')], dropEffect: '' }
    fireEvent.dragEnter(zone, { dataTransfer })
    expect(zone).toHaveAttribute('data-dragging')
    fireEvent.drop(zone, { dataTransfer })
    expect(zone).not.toHaveAttribute('data-dragging')
    expect(onFiles.mock.calls[0]?.[0]).toHaveLength(2)
  })

  it('без multiple берёт один файл, перетаскивание текста игнорирует', () => {
    const onFiles = vi.fn()
    const { container } = renderUi(
      <FileDrop accept=".md" onFiles={onFiles} title="Перетащите документ" />,
    )
    const zone = container.firstElementChild as HTMLElement
    fireEvent.dragEnter(zone, { dataTransfer: { types: ['text/plain'] } })
    expect(zone).not.toHaveAttribute('data-dragging')
    fireEvent.drop(zone, {
      dataTransfer: { types: ['Files'], files: [file('a.md'), file('b.md')] },
    })
    expect(onFiles.mock.calls[0]?.[0]).toHaveLength(1)
  })
})

describe('AudioLevel', () => {
  it('сообщает пиковый уровень и дополняет полосы тишиной', () => {
    renderUi(<AudioLevel levels={[0.2, 0.8, 0.5]} bars={8} label="Уровень сигнала" />)
    const meter = screen.getByRole('meter', { name: 'Уровень сигнала' })
    expect(meter).toHaveAttribute('aria-valuenow', '80')
    expect(meter.children).toHaveLength(8)
  })
})
