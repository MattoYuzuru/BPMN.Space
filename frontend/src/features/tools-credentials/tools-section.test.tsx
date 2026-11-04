import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, waitFor, within } from '@testing-library/react'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { ToolsSection } from './tools-section'

const capability = {
  capability: 'speech_to_text',
  label: 'Распознавание речи',
  description: 'Расшифровка голосовых заметок, аудио и видео со звуком.',
  tool: 'transcribe',
  keys: 1,
  kinds: ['speech_to_text'],
  providers: [
    { id: 'deepgram', label: 'Deepgram' },
    { id: 'openai', label: 'OpenAI' },
  ],
  available: true,
  last_error_code: null,
}

const credential = {
  id: 'c1',
  label: 'Рабочий Deepgram',
  provider: 'deepgram',
  kinds: ['speech_to_text'],
  capabilities: ['speech_to_text'],
  priority: 10,
  enabled: true,
  is_default: false,
  base_url: null,
  default_model: null,
  key_hint: 'abcd',
  monthly_limit: { minutes: 40 },
  exhausted_until: null,
  last_error: null,
  last_error_code: null,
  last_used_at: null,
  created_at: '2026-11-04T10:00:00Z',
}

const list = {
  items: [credential],
  capabilities: [capability],
  storage_available: true,
}

function mount() {
  const calls = stubApi({
    'GET /api/v1/me/credentials': { body: list },
    'POST /api/v1/me/credentials': { status: 201, body: credential },
    'PATCH /api/v1/me/credentials/c1': { body: { ...credential, enabled: false } },
    'POST /api/v1/me/credentials/c1/check': {
      body: { ok: true, detail: 'Ключ работает' },
    },
  })
  const rendered = renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ToolsSection />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { ...rendered, calls }
}

afterEach(() => vi.unstubAllGlobals())

describe('настройки → инструменты', () => {
  it('показывает возможности, ключи, приоритет и лимит', async () => {
    mount()
    await screen.findByText('Рабочий Deepgram')
    expect(screen.getAllByText('Распознавание речи').length).toBeGreaterThan(0)
    expect(screen.getByText('Рабочий Deepgram')).toBeInTheDocument()
    expect(screen.getByText('Приоритет 10')).toBeInTheDocument()
    expect(screen.getByText(/40\s+минут в месяц/)).toBeInTheDocument()
    expect(screen.getByText(/1 ключ/)).toBeInTheDocument()
  })

  it('проверяет ключ и выключает его переключателем', async () => {
    const { user, calls } = mount()
    await screen.findByText('Рабочий Deepgram')
    await user.click(screen.getByRole('button', { name: 'Проверить' }))
    await waitFor(() => expect(calls.some((call) => call.path.endsWith('/check'))).toBe(true))
    await user.click(screen.getByRole('switch', { name: 'Выключить ключ «Рабочий Deepgram»' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'PATCH')).toBe(true))
    expect(calls.find((call) => call.method === 'PATCH')?.body).toMatchObject({ enabled: false })
  })

  it('добавляет ключ: типы задач, провайдер и проверка перед сохранением', async () => {
    const { user, calls } = mount()
    await screen.findByText('Рабочий Deepgram')
    await user.click(screen.getByRole('button', { name: 'Добавить ключ' }))
    const dialog = await screen.findByRole('dialog')
    // По умолчанию выбран тип «Модели»; выбираем распознавание речи.
    await user.click(within(dialog).getByRole('checkbox', { name: /Распознавание речи/ }))
    await user.click(within(dialog).getByRole('checkbox', { name: /^Модели/ }))
    expect(within(dialog).getByText('Где взять ключ')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Ключ'), 'dg-secret')
    await user.click(within(dialog).getByRole('button', { name: 'Проверить и сохранить' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    const post = calls.find((call) => call.method === 'POST')
    expect(post?.body).toMatchObject({
      kinds: ['speech_to_text'],
      provider: 'deepgram',
      api_key: 'dg-secret',
      priority: 100,
      enabled: true,
      is_default: false,
    })
  })
})

describe('правка ключа', () => {
  it('пустые поля лимита снимают ограничение явно', async () => {
    const { user, calls } = mount()
    await screen.findByText('Рабочий Deepgram')
    await user.click(screen.getByRole('button', { name: 'Изменить ключ «Рабочий Deepgram»' }))
    const dialog = await screen.findByRole('dialog')
    const minutes = within(dialog).getByLabelText(/Минуты/)
    expect(minutes).toHaveValue('40')
    await user.clear(minutes)
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'PATCH')).toBe(true))
    expect(calls.find((call) => call.method === 'PATCH')?.body).toMatchObject({
      monthly_limit: null,
      clear_monthly_limit: true,
      default_model: null,
    })
  })
})
