import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import type { Source } from '@/entities/source'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { SourceOcrAction } from './ocr-action'

const scan = (patch: Partial<Source> = {}): Source =>
  ({
    id: 's1',
    project_id: 'p1',
    kind: 'file',
    title: 'Скан регламента',
    file_name: 'scan.pdf',
    content: 'Прочитанная часть',
    status: 'ready',
    active: true,
    origin: 'user',
    trust: 'primary',
    edited_by_human: false,
    created_at: '2026-11-04T10:00:00Z',
    unreadable_pages: [12, 15],
    ...patch,
  }) as Source

function mount(nodes: Source[] = [], canEdit = true) {
  const calls = stubApi({
    'POST /api/v1/sources/s1/ocr': { status: 202, body: scan() },
  })
  renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <SourceOcrAction source={scan()} projectId="p1" canEdit={canEdit} nodes={nodes} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('распознавание страниц', () => {
  it('показывает, сколько страниц без текста, и запускает OCR', async () => {
    const calls = mount()
    expect(screen.getByText(/2\s+страницы без текста/)).toBeInTheDocument()
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Распознать страницы' }))
    await waitFor(() => expect(calls.some((call) => call.path.endsWith('/ocr'))).toBe(true))
  })

  it('во время распознавания показывает прогресс, повтор — после ошибки', async () => {
    const { rerender } = renderUi(
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider>
          <SourceOcrAction
            source={scan()}
            projectId="p1"
            canEdit
            nodes={[
              scan({
                id: 'ocr1',
                origin: 'derived',
                parent_id: 's1',
                status: 'processing',
                derivation: {
                  capability: 'ocr',
                  provider: 'anthropic',
                  created_at: '2026-11-04T10:01:00Z',
                },
              }),
            ]}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    )
    expect(screen.getByText('Распознаю текст страниц')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Распознать/ })).toBeNull()
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider>
          <SourceOcrAction
            source={scan()}
            projectId="p1"
            canEdit
            nodes={[
              scan({
                id: 'ocr1',
                origin: 'derived',
                parent_id: 's1',
                status: 'failed',
                error: 'Провайдер отклонил ключ',
                derivation: {
                  capability: 'ocr',
                  provider: 'anthropic',
                  created_at: '2026-11-04T10:01:00Z',
                },
              }),
            ]}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Провайдер отклонил ключ')
    expect(screen.getByRole('button', { name: 'Повторить распознавание' })).toBeInTheDocument()
  })

  it('без права правки кнопки нет', () => {
    mount([], false)
    expect(screen.queryByRole('button', { name: /Распознать/ })).toBeNull()
  })
})
