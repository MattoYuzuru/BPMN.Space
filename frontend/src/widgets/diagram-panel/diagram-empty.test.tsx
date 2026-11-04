import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen } from '@testing-library/react'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { DiagramEmpty } from './diagram-empty'

const uploads = vi.hoisted(() => ({
  pendingMedia: null as File[] | null,
  confirmMedia: vi.fn(),
  cancelMedia: vi.fn(),
  upload: vi.fn(),
}))

vi.mock('@/features/add-source/use-file-uploads', () => ({
  useFileUploads: () => ({
    uploads: [],
    upload: uploads.upload,
    pendingMedia: uploads.pendingMedia,
    confirmMedia: uploads.confirmMedia,
    cancelMedia: uploads.cancelMedia,
  }),
}))

const workspace = {
  project: { id: 'p1', sources: [], questions: [], status: 'empty' },
  canEdit: true,
}

vi.mock('@/widgets/workspace/model', () => ({
  useWorkspace: () => workspace,
  useWorkspaceUi: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({ setDialog: vi.fn(), openRunDialog: vi.fn() }),
}))

vi.mock('@/features/add-source/media-duration', () => ({
  mediaFileInfo: async () => ({ durationSec: 300, hasVideo: true }),
}))

const estimate = {
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
}

function mount() {
  stubApi({ 'POST /api/v1/projects/p1/sources/media/estimate': { body: estimate } })
  return renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <DiagramEmpty />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  uploads.pendingMedia = null
  vi.unstubAllGlobals()
})

it('выбранная с пустого экрана запись открывает выбор профиля и загружается через него', async () => {
  const { unmount } = mount()
  expect(screen.queryByText('Как обработать запись')).toBeNull()
  unmount()

  uploads.pendingMedia = [new File(['x'], 'встреча.mp4', { type: 'video/mp4' })]
  const { user } = mount()
  expect(await screen.findByText('Как обработать запись')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /Загрузить 1 файл/ }))
  expect(uploads.confirmMedia).toHaveBeenCalledWith('sparse')
})
