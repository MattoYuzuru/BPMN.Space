import { render, screen } from '@testing-library/react'
import { LazyDiagramEditor, preloadDiagramEditor } from './LazyDiagramEditor'

// Настоящий bpmn-js в jsdom не нужен: проверяем только ленивую обёртку.
vi.mock('./DiagramEditor', () => ({
  default: ({ className, xml }: { className?: string; xml: string }) => (
    <div data-testid="editor" className={className}>
      {xml}
    </div>
  ),
}))

describe('LazyDiagramEditor', () => {
  it('пока чанк грузится, держит место пустым блоком того же размера', async () => {
    const { container } = render(<LazyDiagramEditor xml="<a/>" className="h-full flex-1" />)
    const placeholder = container.firstElementChild
    expect(placeholder?.getAttribute('aria-busy')).toBe('true')
    expect(placeholder?.className).toBe('h-full flex-1')
    expect(placeholder?.textContent).toBe('')
    expect(await screen.findByTestId('editor')).toHaveTextContent('<a/>')
  })

  it('показывает переданный fallback', () => {
    render(<LazyDiagramEditor xml="<a/>" fallback={<p>Скелетон</p>} />)
    expect(screen.queryByText('Скелетон') ?? screen.queryByTestId('editor')).not.toBeNull()
  })

  it('preloadDiagramEditor загружает модуль редактора', async () => {
    const module = (await preloadDiagramEditor()) as { default: unknown }
    expect(typeof module.default).toBe('function')
  })
})
