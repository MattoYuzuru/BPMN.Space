import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, within } from '@testing-library/react'
import type { Source } from '@/entities/source'
import { renderUi } from '@/test/render'
import { useWorkspaceUi, type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { SourceSheet } from './source-sheet'
import { SourcesPanel } from './sources-panel'

const base = {
  project_id: 'p1',
  active: true,
  created_at: '2026-11-04T10:00:00Z',
  origin: 'user',
  trust: 'primary',
  edited_by_human: false,
} as const

const record: Source = {
  ...base,
  id: 'rec',
  kind: 'file',
  title: 'встреча.mp4',
  file_name: 'встреча.mp4',
  content: '',
  status: 'ready',
  duration_sec: 125,
  media: { has_audio: true, has_video: true },
}
const transcript: Source = {
  ...base,
  id: 'tr',
  kind: 'text',
  title: 'Расшифровка: встреча.mp4',
  content: '[00:00] Диспетчер согласует заявку.\n[00:30] Инженер готовит акт.',
  status: 'ready',
  origin: 'derived',
  trust: 'extracted',
  parent_id: 'rec',
  edited_by_human: true,
  derivation: {
    capability: 'speech_to_text',
    provider: 'deepgram',
    model: 'nova-3',
    params: { segment_sec: 600 },
    created_at: '2026-11-04T10:01:00Z',
  },
}
const rules: Source = {
  ...base,
  id: 'txt',
  kind: 'text',
  title: 'Регламент',
  content: 'Инженер готовит заявку.',
  status: 'ready',
}

function workspace(sources: Source[], canEdit = false) {
  const openSource = vi.fn()
  const value = {
    project: { id: 'p1', sources, questions: [], latest_version: null },
    canEdit,
    openSource,
    selectQuestion: vi.fn(),
    focusElements: vi.fn(),
  } as unknown as WorkspaceApi
  return { value, openSource }
}

function renderPanel(sources: Source[]) {
  const { value, openSource } = workspace(sources)
  const rendered = renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <WorkspaceContext.Provider value={value}>
        <SourcesPanel onCollapse={vi.fn()} />
      </WorkspaceContext.Provider>
    </QueryClientProvider>,
  )
  return { ...rendered, openSource }
}

function renderSheet(sources: Source[], sourceId: string, canEdit = false) {
  const { value, openSource } = workspace(sources, canEdit)
  const rendered = renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <WorkspaceContext.Provider value={value}>
        <SourceSheet sourceId={sourceId} onClose={vi.fn()} />
      </WorkspaceContext.Provider>
    </QueryClientProvider>,
  )
  return { ...rendered, openSource }
}

afterEach(() => useWorkspaceUi.getState().reset())

it('показывает запись деревом: расшифровка вложена, с меткой «ИИ», провайдером и правкой', async () => {
  const { user, openSource } = renderPanel([record, transcript, rules])
  const region = screen.getByRole('region', { name: 'Источники' })
  // Счётчик — все материалы дерева: исходные и производные узлы.
  expect(within(region).getByText('3')).toBeInTheDocument()
  expect(within(region).getByText('Видеозапись')).toBeInTheDocument()

  const derived = screen.getByRole('list', { name: 'Получено из «встреча.mp4»' })
  const link = within(derived).getByRole('link', { name: /Расшифровка: встреча\.mp4/ })
  expect(within(derived).getByText('ИИ')).toBeInTheDocument()
  expect(within(derived).getByText('Deepgram, nova-3')).toBeInTheDocument()
  expect(within(derived).getByText('изменено человеком')).toBeInTheDocument()
  expect(within(derived).queryByText('Регламент')).not.toBeInTheDocument()

  await user.click(link)
  expect(openSource).toHaveBeenCalledWith('tr')
})

it('показывает уровень доверия, стоимость обработки, страницы без текста и метку агента', () => {
  const scan: Source = {
    ...rules,
    id: 'scan',
    title: 'Скан регламента',
    file_name: 'scan.pdf',
    kind: 'file',
    trust: 'extracted',
    unreadable_pages: [12, 15],
    warning: 'Часть страниц без текста',
  }
  const agentNote: Source = {
    ...base,
    id: 'agent',
    kind: 'text',
    title: 'Конспект агента',
    content: 'Материал принёс агент.',
    status: 'ready',
    origin: 'agent',
    trust: 'agent',
  }
  renderPanel([
    {
      ...transcript,
      derivation: {
        capability: 'speech_to_text',
        provider: 'deepgram',
        model: 'nova-3',
        created_at: '2026-11-04T10:01:00Z',
        cost_usd: 0.42,
      },
    },
    record,
    scan,
    agentNote,
  ])
  expect(screen.getAllByText('извлечено').length).toBeGreaterThan(0)
  expect(screen.getByText('$0,42')).toBeInTheDocument()
  expect(screen.getByText(/2\s+страницы без текста/)).toBeInTheDocument()
  // «Агент» — отдельная метка, уровень доверия «от агента» не дублируется.
  expect(screen.getByText('Агент')).toBeInTheDocument()
  expect(screen.queryByText('от агента')).toBeNull()
})

it('сбой расшифровки виден и на записи, и на производном узле', () => {
  const error = 'В файле нет звуковой дорожки'
  renderPanel([
    { ...record, status: 'failed', error },
    { ...transcript, status: 'failed', error, content: '', edited_by_human: false },
  ])
  expect(screen.getAllByText(error)).toHaveLength(2)
})

it('пока запись обрабатывается, узлы подписаны по смыслу', () => {
  renderPanel([
    { ...record, status: 'processing' },
    { ...transcript, status: 'processing', content: '' },
  ])
  expect(screen.getAllByText('Обрабатываю запись').length).toBeGreaterThan(0)
  expect(screen.getAllByText('Расшифровываю запись').length).toBeGreaterThan(0)
})

it('расшифровка показывает таймкоды и отметку правки человеком', () => {
  renderSheet([record, transcript], 'tr')
  const body = screen.getByTestId('source-content')
  const codes = body.querySelectorAll('[data-timecode]')
  expect([...codes].map((node) => node.textContent)).toEqual(['[00:00]', '[00:30]'])
  expect(screen.getByText('Изменено человеком')).toBeInTheDocument()
  expect(screen.getByText('Deepgram, nova-3')).toBeInTheDocument()
})

it('запись без своего текста ведёт к производным узлам и не правится', async () => {
  const { user, openSource } = renderSheet([record, transcript], 'rec', true)
  const container = screen.getByTestId('media-container')
  expect(within(container).getByText('Есть звук')).toBeInTheDocument()
  expect(within(container).getByText('Есть видео')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Править текст' })).not.toBeInTheDocument()
  await user.click(within(container).getByRole('button', { name: 'Расшифровка: встреча.mp4' }))
  expect(openSource).toHaveBeenCalledWith('tr')
})

it('неудавшуюся расшифровку можно вписать вручную с предупреждением о правке', async () => {
  const { user } = renderSheet(
    [{ ...transcript, status: 'failed', error: 'Сбой', content: '', edited_by_human: false }],
    'tr',
    true,
  )
  await user.click(screen.getByRole('button', { name: 'Править текст' }))
  expect(screen.getByText(/узел будет отмечен «Изменено человеком»/)).toBeInTheDocument()
})
