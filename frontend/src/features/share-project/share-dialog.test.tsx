import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { ShareDialog } from './share-dialog'

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  }),
}))

const PROJECT = 'p-1'
const LINKS = `/api/v1/projects/${PROJECT}/share-links`
const MEMBERS = `/api/v1/projects/${PROJECT}/members`

const existingLink = {
  id: 'link-1',
  role: 'viewer',
  created_at: '2026-10-01T10:00:00Z',
  expires_at: '2036-10-31T10:00:00Z',
  revoked_at: null,
}

function Harness() {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Снова открыть
      </button>
      <ShareDialog projectId={PROJECT} open={open} onOpenChange={setOpen} />
    </>
  )
}

function setup() {
  const user = userEvent.setup()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <Harness />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user }
}

afterEach(() => {
  vi.unstubAllGlobals()
  toastSuccess.mockReset()
  toastError.mockReset()
})

describe('ShareDialog', () => {
  it('сроки зависят от роли, а недопустимый срок при смене роли сбрасывается', async () => {
    stubApi({ [`GET ${LINKS}`]: { body: [] }, [`GET ${MEMBERS}`]: { body: [] } })
    const { user } = setup()
    const expiry = await screen.findByRole('combobox', { name: 'Срок действия' })
    expect(expiry).toHaveTextContent('30 дней')

    await user.click(expiry)
    expect((await screen.findAllByRole('option')).map((o) => o.textContent)).toEqual([
      '7 дней',
      '30 дней',
      '3 месяца',
      'Год',
    ])
    await user.click(screen.getByRole('option', { name: 'Год' }))

    await user.click(screen.getByRole('radio', { name: /Редактирование/ }))
    expect(screen.getByRole('combobox', { name: 'Срок действия' })).toHaveTextContent('7 дней')
    await user.click(screen.getByRole('combobox', { name: 'Срок действия' }))
    expect((await screen.findAllByRole('option')).map((o) => o.textContent)).toEqual([
      '1 день',
      '7 дней',
      '30 дней',
    ])
  })

  it('показывает полный адрес только сразу после создания и копирует его', async () => {
    const calls = stubApi({
      [`GET ${LINKS}`]: { body: [] },
      [`GET ${MEMBERS}`]: { body: [] },
      [`POST ${LINKS}`]: {
        status: 201,
        body: {
          id: 'link-2',
          role: 'viewer',
          url_path: '/share/secret-token',
          created_at: '2026-10-04T10:00:00Z',
          expires_at: '2036-11-03T10:00:00Z',
        },
      },
    })
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Создать ссылку' }))

    const url = `${window.location.origin}/share/secret-token`
    const field = await screen.findByDisplayValue(url)
    expect(field).toHaveAttribute('readonly')
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      role: 'viewer',
      expires_in_days: 30,
    })

    await user.click(screen.getByRole('button', { name: 'Копировать ссылку' }))
    expect(await navigator.clipboard.readText()).toBe(url)
    expect(toastSuccess).toHaveBeenCalledWith('Ссылка скопирована')

    // Окно закрыли и открыли снова: адреса нигде нет, токен не сохранился.
    await user.click(screen.getByRole('button', { name: 'Закрыть' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Снова открыть' }))
    await screen.findByRole('dialog')
    expect(screen.queryByDisplayValue(url)).not.toBeInTheDocument()
    expect(screen.queryByText(/secret-token/)).not.toBeInTheDocument()
  })

  it('отзывает ссылку после подтверждения и убирает её из списка', async () => {
    let links = [existingLink]
    const calls = stubApi({
      [`GET ${LINKS}`]: () => ({ body: links }),
      [`GET ${MEMBERS}`]: { body: [] },
      [`DELETE ${LINKS}/link-1`]: () => {
        links = []
        return { status: 204 }
      },
    })
    const { user } = setup()
    const list = await screen.findByRole('list', { name: 'Действующие ссылки' })
    expect(within(list).getByText('Просмотр')).toBeInTheDocument()

    await user.click(within(list).getByRole('button', { name: 'Отозвать ссылку' }))
    const confirm = await screen.findByRole('alertdialog', { name: 'Отозвать ссылку?' })
    // Подтверждение ещё ничего не отозвало.
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    await user.click(within(confirm).getByRole('button', { name: 'Отозвать' }))

    await waitFor(() =>
      expect(calls.some((call) => call.method === 'DELETE' && call.path.endsWith('/link-1'))).toBe(
        true,
      ),
    )
    await screen.findByText('Ссылок пока нет')
    expect(toastSuccess).toHaveBeenCalledWith('Ссылка отозвана')
  })

  it('показывает участников и убирает по подтверждению', async () => {
    let members = [
      {
        user_id: 'u-9',
        email: 'anna.petrova@company.ru',
        role: 'editor',
        added_at: '2026-10-02T10:00:00Z',
      },
    ]
    const calls = stubApi({
      [`GET ${LINKS}`]: { body: [] },
      [`GET ${MEMBERS}`]: () => ({ body: members }),
      [`DELETE ${MEMBERS}/u-9`]: () => {
        members = []
        return { status: 204 }
      },
    })
    const { user } = setup()
    await user.click(await screen.findByRole('tab', { name: /Участники/ }))
    expect(await screen.findByText('anna.petrova@company.ru')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Убрать участника' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Убрать' }),
    )
    await screen.findByText('Участников пока нет')
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true)
  })

  it('ошибка создания — тост, а не поле: ссылки нет, форма на месте', async () => {
    stubApi({
      [`GET ${LINKS}`]: { body: [] },
      [`GET ${MEMBERS}`]: { body: [] },
      [`POST ${LINKS}`]: { status: 403, body: { detail: 'Ссылки создаёт только владелец' } },
    })
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Создать ссылку' }))
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        'Не удалось создать ссылку',
        expect.objectContaining({ description: 'Ссылки создаёт только владелец' }),
      ),
    )
    expect(screen.getByRole('button', { name: 'Создать ссылку' })).toBeEnabled()
  })
})
