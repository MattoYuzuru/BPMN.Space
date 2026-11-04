import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { CredentialsSection } from './credentials-section'

const SECRET = 'sk-ant-api03-VERY-SECRET-1234'

const saved = {
  id: 'c1',
  provider: 'anthropic',
  label: 'Рабочий',
  base_url: null,
  key_hint: '1234',
  default_model: 'claude-opus-5-5',
  is_default: true,
  created_at: '2026-11-01T00:00:00Z',
  last_used_at: null,
  last_error: null,
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <CredentialsSection />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user }
}

const OPUS_CAPS = {
  known: true,
  context_tokens: 1_000_000,
  max_output_tokens: 128_000,
  vision: true,
  pdf_input: true,
  tools: true,
  effort_levels: ['low', 'medium', 'high', 'xhigh', 'max'],
  effort_default: 'medium',
  accepts_temperature: false,
  prices: {
    input: 4,
    output: 20,
    cache_read: 0.2,
    cache_write: 5,
    currency: 'USD',
    checked_on: '2026-10-06',
    note: null,
  },
}

afterEach(() => vi.unstubAllGlobals())

describe('Модели и ключи', () => {
  it('показывает ключи с маской и последней ошибкой, но не сам ключ', async () => {
    stubApi({
      'GET /api/v1/me/llm-credentials': {
        body: {
          items: [{ ...saved, last_error: 'Провайдер отклонил ключ (HTTP 401)' }],
          storage_available: true,
        },
      },
    })
    mount()
    expect(await screen.findByText('Рабочий')).toBeInTheDocument()
    expect(screen.getByText('По умолчанию')).toBeInTheDocument()
    expect(screen.getByText('••••1234')).toBeInTheDocument()
    expect(screen.getByText('Claude Opus 5.5')).toBeInTheDocument()
    expect(screen.getByText(/отклонил ключ/)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain(SECRET)
  })

  it('пустой список объясняет, что работает модель сервера', async () => {
    stubApi({
      'GET /api/v1/me/llm-credentials': { body: { items: [], storage_available: true } },
    })
    mount()
    expect(await screen.findByText('Своих ключей нет')).toBeInTheDocument()
  })

  it('без шифрования на сервере добавление недоступно', async () => {
    stubApi({
      'GET /api/v1/me/llm-credentials': { body: { items: [], storage_available: false } },
    })
    mount()
    expect(await screen.findByText(/не настроено на сервере/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Добавить ключ' })).toBeDisabled()
  })

  it('добавляет ключ в два шага: проверка и выбор модели', async () => {
    const calls = stubApi({
      'GET /api/v1/me/llm-credentials': { body: { items: [], storage_available: true } },
      'POST /api/v1/me/llm-credentials': { status: 201, body: saved },
      'GET /api/v1/me/llm-credentials/c1/models': {
        body: {
          items: [
            { id: 'claude-opus-5-5', label: 'Claude Opus 5.5', capabilities: OPUS_CAPS },
            { id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', capabilities: OPUS_CAPS },
          ],
        },
      },
      'PATCH /api/v1/me/llm-credentials/c1': {
        body: { ...saved, default_model: 'claude-sonnet-5-5' },
      },
    })
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Добавить ключ' }))
    const dialog = await screen.findByRole('dialog')
    const keyInput = within(dialog).getByLabelText('API-ключ') as HTMLInputElement
    expect(keyInput.type).toBe('password')
    await user.type(keyInput, SECRET)
    await user.click(within(dialog).getByRole('button', { name: 'Показать ключ' }))
    expect(keyInput.type).toBe('text')
    await user.click(within(dialog).getByRole('button', { name: 'Проверить и сохранить' }))

    const post = calls.find(
      (call) => call.method === 'POST' && call.path.endsWith('llm-credentials'),
    )
    expect(post?.body).toMatchObject({ provider: 'anthropic', api_key: SECRET })
    await screen.findByText('Выберите модель')
    // Возможности модели по умолчанию видны сразу под выбором (пробелы нормализуются).
    expect(
      await screen.findByText(/Окно 1 млн токенов · ответ до 128 тыс\. токенов/),
    ).toBeInTheDocument()
    expect(screen.getByText(/\$4 \/ \$20 за 1 млн токенов/)).toBeInTheDocument()
    const select = await screen.findByRole('combobox', { name: 'Модель по умолчанию' })
    select.focus()
    await user.keyboard('{Enter}')
    await user.click(await screen.findByRole('option', { name: 'Claude Sonnet 5.5' }))
    await user.click(screen.getByRole('button', { name: 'Готово' }))
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === 'PATCH' && JSON.stringify(call.body).includes('claude-sonnet-5-5'),
        ),
      ).toBe(true),
    )
  })

  it('ошибка проверки показывается у поля, а введённое остаётся для правки', async () => {
    stubApi({
      'GET /api/v1/me/llm-credentials': { body: { items: [], storage_available: true } },
      'POST /api/v1/me/llm-credentials': {
        status: 422,
        body: { detail: 'Провайдер отклонил ключ (HTTP 401). Проверьте ключ' },
      },
    })
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Добавить ключ' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('API-ключ'), 'sk-wrong-key')
    await user.click(within(dialog).getByRole('button', { name: 'Проверить и сохранить' }))
    expect(await within(dialog).findByText(/отклонил ключ/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText('API-ключ')).toHaveValue('sk-wrong-key')
  })

  it('совместимому провайдеру нужен адрес API', async () => {
    stubApi({
      'GET /api/v1/me/llm-credentials': { body: { items: [], storage_available: true } },
    })
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Добавить ключ' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByLabelText('Адрес API')).toBeNull()
    await user.click(within(dialog).getByRole('radio', { name: 'Совместимый с OpenAI' }))
    await user.type(within(dialog).getByLabelText('API-ключ'), 'sk-something-long')
    const submit = within(dialog).getByRole('button', { name: 'Проверить и сохранить' })
    expect(submit).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Адрес API'), 'https://openrouter.ai/api/v1')
    expect(submit).toBeEnabled()
  })

  it('удаляет ключ после подтверждения', async () => {
    const calls = stubApi({
      'GET /api/v1/me/llm-credentials': { body: { items: [saved], storage_available: true } },
      'DELETE /api/v1/me/llm-credentials/c1': { status: 204 },
    })
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Удалить ключ «Рабочий»' }))
    const confirm = await screen.findByRole('alertdialog')
    await user.click(within(confirm).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'DELETE')).toBe(true))
  })
})
