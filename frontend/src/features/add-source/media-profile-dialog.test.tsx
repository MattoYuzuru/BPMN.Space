import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { MediaProfileDialog } from './media-profile-dialog'

vi.mock('./media-duration', () => ({
  mediaFileInfo: async () => ({ durationSec: 300, hasVideo: true }),
}))

afterEach(() => vi.unstubAllGlobals())

it('показывает профили и оценку, возвращает выбранный профиль', async () => {
  const calls = stubApi({
    'POST /api/v1/projects/p1/sources/media/estimate': {
      body: {
        media_profile: 'sparse',
        media_profile_label: 'Звук + редкие кадры',
        duration_sec: 300,
        currency: 'USD',
        stt: { minutes: 5, cost_usd: { min_usd: 0.1, max_usd: 0.2 } },
        frames: {
          count_min: 5,
          count_max: 12,
          vision_requests: 1,
          cost_usd: { min_usd: 0.05, max_usd: 0.1 },
        },
        total_cost_usd: { min_usd: 0.15, max_usd: 0.3 },
        note: 'Оценка зависит от ключей',
        priced_on: '2026-11-04',
      },
    },
  })
  const onConfirm = vi.fn()
  const { user } = renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <MediaProfileDialog
          projectId="p1"
          files={[new File(['x'], 'встреча.mp4', { type: 'video/mp4' })]}
          onCancel={vi.fn()}
          onConfirm={onConfirm}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  expect(screen.getByText('Только звук')).toBeInTheDocument()
  expect(screen.getByText('Подробно')).toBeInTheDocument()
  await waitFor(() =>
    expect(calls.some((call) => call.path.endsWith('/media/estimate'))).toBe(true),
  )
  expect(await screen.findByText(/Итого:/)).toBeInTheDocument()
  expect(screen.getByText(/Запись уходит выбранному провайдеру/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /Звук \+ редкие кадры/ }))
  await user.click(screen.getByRole('button', { name: /Загрузить 1 файл/ }))
  expect(onConfirm).toHaveBeenCalledWith('sparse')
})
