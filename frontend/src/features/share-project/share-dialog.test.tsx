import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { TooltipProvider, toast } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { ShareDialog } from './share-dialog'
import { ShareCreateForm } from './share-parts'

const toastSuccess = vi.fn()
const toastError = vi.fn()
// Шпионим за самим объектом уведомлений: через него идут и тосты фичи, и тосты useCopy.
vi.spyOn(toast, 'success').mockImplementation((...args) => {
  toastSuccess(...args)
  return ''
})
vi.spyOn(toast, 'error').mockImplementation((...args) => {
  toastError(...args)
  return ''
})

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
  it('просмотр и редактирование предлагают одинаковые сроки', async () => {
    stubApi({ [`GET ${LINKS}`]: { body: [] }, [`GET ${MEMBERS}`]: { body: [] } })
    const { user } = setup()
    const expiry = await screen.findByRole('combobox', { name: 'Срок действия' })
    expect(expiry).toHaveTextContent('30 дней')

    await user.click(expiry)
    expect((await screen.findAllByRole('option')).map((o) => o.textContent)).toEqual([
      '7 дней',
      '30 дней',
      'Год',
      'Бессрочно',
    ])
    await user.click(screen.getByRole('option', { name: 'Год' }))

    await user.click(screen.getByRole('radio', { name: /Редактирование/ }))
    expect(screen.getByRole('combobox', { name: 'Срок действия' })).toHaveTextContent('Год')
    await user.click(screen.getByRole('combobox', { name: 'Срок действия' }))
    expect((await screen.findAllByRole('option')).map((o) => o.textContent)).toEqual([
      '7 дней',
      '30 дней',
      'Год',
      'Бессрочно',
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

  it('копирует адрес только что созданной ссылки и из списка, пока окно открыто', async () => {
    const created = {
      id: 'link-2',
      role: 'viewer',
      created_at: '2026-10-04T10:00:00Z',
      expires_at: '2036-11-03T10:00:00Z',
      revoked_at: null,
    }
    let links: unknown[] = []
    stubApi({
      [`GET ${LINKS}`]: () => ({ body: links }),
      [`GET ${MEMBERS}`]: { body: [] },
      [`POST ${LINKS}`]: () => {
        links = [created]
        return {
          status: 201,
          body: {
            ...created,
            url_path: '/share/session-token',
          },
        }
      },
    })
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Создать ссылку' }))
    const list = await screen.findByRole('list', { name: 'Действующие ссылки' })
    await user.click(within(list).getByRole('button', { name: 'Копировать ссылку' }))
    expect(await navigator.clipboard.readText()).toBe(
      `${window.location.origin}/share/session-token`,
    )
    expect(toastSuccess).toHaveBeenCalledWith('Ссылка скопирована')
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

describe('ShareDialog: проверка коллегой', () => {
  const PROJECT_URL = `/api/v1/projects/${PROJECT}`
  const project = {
    id: PROJECT,
    title: 'Закупка',
    access: 'owner',
    lanes: ['Продажи', 'Склад'],
    sources: [],
    questions: [],
  }

  function reviewerStubs(createdLaneIds: string[] = ['Lane_Sales']) {
    return stubApi({
      [`GET ${LINKS}`]: { body: [] },
      [`GET ${MEMBERS}`]: { body: [] },
      [`GET ${PROJECT_URL}`]: { body: project },
      [`POST ${LINKS}`]: {
        status: 201,
        body: {
          id: 'link-r',
          role: 'reviewer',
          url_path: '/share/review-secret',
          created_at: '2026-10-04T10:00:00Z',
          expires_at: '2026-11-03T10:00:00Z',
          lane_ids: createdLaneIds,
        },
      },
      'GET /api/v1/shares/review-secret/agent-prompt': {
        body: {
          text: 'Проверьте дорожку «Продажи» и ответьте на вопросы.',
          lane_ids: ['Lane_Sales'],
          lanes: ['Продажи'],
          questions_recap: [],
          whole_project: false,
        },
      },
    })
  }

  it('третья роль, область-дорожки и отправка lane_ids', async () => {
    const calls = reviewerStubs()
    const { user } = setup()
    await user.click(await screen.findByRole('radio', { name: /Проверка/ }))
    await user.click(await screen.findByRole('radio', { name: 'Выбранные дорожки' }))
    await user.click(await screen.findByRole('checkbox', { name: 'Продажи' }))
    await user.click(screen.getByRole('button', { name: 'Создать ссылку' }))

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      role: 'reviewer',
      expires_in_days: 30,
      lane_ids: ['Продажи'],
    })
    expect(await screen.findByText('Выбранные дорожки (1)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Запрос для агента' })).toBeVisible()
  })

  it('весь проект допустим без выбранных дорожек', async () => {
    const calls = reviewerStubs([])
    const { user } = setup()
    await user.click(await screen.findByRole('radio', { name: /Проверка/ }))
    await user.click(screen.getByRole('button', { name: 'Создать ссылку' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      role: 'reviewer',
      expires_in_days: 30,
    })
    expect(await screen.findByText('Весь проект')).toBeInTheDocument()
  })

  it('режим выбранных дорожек без отметки не отправляет форму', async () => {
    const calls = reviewerStubs()
    const { user } = setup()
    await user.click(await screen.findByRole('radio', { name: /Проверка/ }))
    await user.click(await screen.findByRole('radio', { name: 'Выбранные дорожки' }))
    expect(await screen.findByText(/Отметьте хотя бы одну дорожку/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Создать ссылку' })).toBeDisabled()
    expect(calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('у просмотра области дорожек нет', async () => {
    stubApi({ [`GET ${LINKS}`]: { body: [] }, [`GET ${MEMBERS}`]: { body: [] } })
    setup()
    expect(await screen.findByRole('radio', { name: /Просмотр/ })).toBeInTheDocument()
    expect(screen.queryByText('Область проверки')).not.toBeInTheDocument()
    expect(screen.queryByText('Выбранные дорожки')).not.toBeInTheDocument()
  })

  it('копирует готовый запрос для агента, а секрет ссылки в текст не попадает', async () => {
    reviewerStubs()
    const { user } = setup()
    await user.click(await screen.findByRole('radio', { name: /Проверка/ }))
    await user.click(screen.getByRole('button', { name: 'Создать ссылку' }))
    await user.click(await screen.findByRole('button', { name: 'Запрос для агента' }))
    const dialog = await screen.findByRole('dialog', { name: 'Запрос для агента' })
    const text = within(dialog).getByLabelText('Текст запроса') as HTMLTextAreaElement
    expect(text.value).toBe('Проверьте дорожку «Продажи» и ответьте на вопросы.')
    expect(text).toHaveAttribute('readonly')
    expect(document.body.textContent).not.toContain('review-secret')
    // Секрет ссылки не должен просачиваться в значения полей этого окна (кроме самого адреса).
    const values = [...document.querySelectorAll('input, textarea')]
      .map((element) => (element as HTMLInputElement).value)
      .filter((value) => value !== `${window.location.origin}/share/review-secret`)
    expect(values.join(' ')).not.toContain('review-secret')
    await user.click(within(dialog).getByRole('button', { name: 'Копировать запрос' }))
    expect(await navigator.clipboard.readText()).toBe(text.value)
    expect(toastSuccess).toHaveBeenCalledWith('Запрос скопирован')
  })

  it('список ссылок показывает роль и область проверки', async () => {
    stubApi({
      [`GET ${LINKS}`]: {
        body: [
          {
            id: 'r1',
            role: 'reviewer',
            created_at: '2026-10-01T10:00:00Z',
            expires_at: '2036-10-31T10:00:00Z',
            revoked_at: null,
            lane_ids: ['Lane_Sales', 'Lane_Warehouse'],
          },
        ],
      },
      [`GET ${MEMBERS}`]: { body: [] },
    })
    setup()
    const list = await screen.findByRole('list', { name: 'Действующие ссылки' })
    expect(within(list).getByText('Проверка')).toBeInTheDocument()
    expect(within(list).getByText('Выбранные дорожки (2)')).toBeInTheDocument()
  })
})

it('пустая схема с выбранными дорожками не блокирует ссылку без объяснения', async () => {
  const onCreate = vi.fn()
  const user = userEvent.setup()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        {/* biome-ignore lint/a11y/useValidAriaRole: role — проп проверки, не ARIA-роль */}
        <ShareCreateForm
          role="reviewer"
          days={30}
          scope="selected"
          lanes={[]}
          selectedLanes={[]}
          onRoleChange={vi.fn()}
          onDaysChange={vi.fn()}
          onScopeChange={vi.fn()}
          onLanesChange={vi.fn()}
          onCreate={onCreate}
          lanesLoading={false}
          lanesError={false}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  const submit = screen.getByRole('button', { name: 'Создать ссылку' })
  expect(submit).toBeEnabled()
  expect(screen.queryByRole('alert')).toBeNull()
  await user.click(submit)
  expect(onCreate).toHaveBeenCalled()
})
