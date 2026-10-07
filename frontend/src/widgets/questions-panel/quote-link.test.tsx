import { screen } from '@testing-library/react'
import type { Source } from '@/entities/source'
import { renderUi } from '@/test/render'
import { type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { QuoteLink } from './quote-link'

const quote = { source_id: 's1', quote: 'Инженер проверяет заявку.' }

it('открывает источник по цитате и завершает предыдущую панель', async () => {
  const openSource = vi.fn()
  const onNavigate = vi.fn()
  const { user } = renderUi(
    <WorkspaceContext.Provider value={{ openSource } as unknown as WorkspaceApi}>
      <QuoteLink
        quote={quote}
        source={{ id: 's1', title: 'Регламент', kind: 'text' } as Source}
        onNavigate={onNavigate}
      />
    </WorkspaceContext.Provider>,
  )
  const link = screen.getByRole('link')
  expect(link).toHaveAttribute('href', `?source=s1&mark=${encodeURIComponent(quote.quote)}`)
  await user.click(link)
  expect(onNavigate).toHaveBeenCalledOnce()
  expect(openSource).toHaveBeenCalledWith('s1', quote.quote)
})

it('сохраняет цитату удалённого источника без неработающей ссылки', () => {
  renderUi(
    <WorkspaceContext.Provider value={{ openSource: vi.fn() } as unknown as WorkspaceApi}>
      <QuoteLink quote={quote} />
    </WorkspaceContext.Provider>,
  )
  expect(screen.getByText('Источник удалён или недоступен')).toBeVisible()
  expect(screen.getByText(`«${quote.quote}»`)).toBeVisible()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
