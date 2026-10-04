import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider } from '@/shared/lib/theme'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { SharePage } from './share-page'

window.scrollTo = vi.fn()

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  }),
}))
// Рабочее место тяжёлое (панели, bpmn-js): проверяем, что страница передаёт ему, а не его самого.
vi.mock('./shared-workspace', () => ({
  SharedWorkspace: (props: { shared: { detail: { title: string } }; openProject: boolean }) => (
    <div data-testid="workspace" data-open-project={String(props.openProject)}>
      {props.shared.detail.title}
    </div>
  ),
}))

const TOKEN = 'tok'
const SHARE = `/api/v1/shares/${TOKEN}`
const user = (email: string) => ({ id: 'u1', email })
const guestSession = { auth_enabled: true, user: null }
const signedSession = { auth_enabled: true, user: user('anna@company.ru') }
const detail = { id: 'p1', title: 'Закупка оборудования', access: 'viewer', sources: [] }
const shared = (role: 'viewer' | 'editor') => ({
  role,
  editor_requires_account: role === 'editor',
  detail,
})

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const root = createRootRoute({ component: Outlet })
  const routes = [
    createRoute({
      getParentRoute: () => root,
      path: '/share/$token',
      component: () => <SharePage token={TOKEN} search={{}} onSearchChange={() => {}} />,
    }),
    createRoute({ getParentRoute: () => root, path: '/', component: () => <p>Главная</p> }),
    createRoute({ getParentRoute: () => root, path: '/login', component: () => <p>Вход</p> }),
    createRoute({
      getParentRoute: () => root,
      path: '/projects/$projectId',
      component: () => <p>Страница проекта</p>,
    }),
  ]
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: [`/share/${TOKEN}`] }),
  })
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <TooltipProvider>
          <RouterProvider router={router} />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
  return { router }
}

afterEach(() => {
  vi.unstubAllGlobals()
  toastSuccess.mockReset()
  toastError.mockReset()
})

describe('страница по ссылке: просмотр', () => {
  it('гость открывает ссылку на просмотр без входа и видит «Войти» в шапке', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: guestSession },
      [`GET ${SHARE}`]: { body: shared('viewer') },
    })
    mount()
    const workspace = await screen.findByTestId('workspace')
    expect(workspace).toHaveTextContent('Закупка оборудования')
    expect(workspace).toHaveAttribute('data-open-project', 'false')
  })

  it('вошедший владелец или редактор получает переход в проект', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: signedSession },
      [`GET ${SHARE}`]: { body: shared('viewer') },
      'GET /api/v1/projects/p1': { body: { ...detail, access: 'owner' } },
    })
    mount()
    await waitFor(() =>
      expect(screen.getByTestId('workspace')).toHaveAttribute('data-open-project', 'true'),
    )
  })

  it('вошедший без доступа к проекту остаётся зрителем', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: signedSession },
      [`GET ${SHARE}`]: { body: shared('viewer') },
      'GET /api/v1/projects/p1': { status: 404, body: { detail: 'Проект не найден' } },
    })
    mount()
    const workspace = await screen.findByTestId('workspace')
    expect(workspace).toHaveAttribute('data-open-project', 'false')
  })
})

describe('страница по ссылке: приглашение редактора', () => {
  it('гость (401) входит с возвратом на эту же ссылку', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: guestSession },
      [`GET ${SHARE}`]: { status: 401, body: { detail: 'Войдите' } },
    })
    mount()
    const link = await screen.findByRole('link', { name: 'Войти, чтобы принять' })
    expect(link).toHaveAttribute('href', `/login?redirect=${encodeURIComponent(`/share/${TOKEN}`)}`)
    expect(screen.queryByRole('button', { name: 'Принять приглашение' })).not.toBeInTheDocument()
  })

  it('вошедший видит проект и принимает приглашение: переход в проект и уведомление', async () => {
    const calls = stubApi({
      'GET /api/v1/auth/session': { body: signedSession },
      [`GET ${SHARE}`]: { body: shared('editor') },
      'GET /api/v1/projects/p1': { status: 404, body: { detail: 'Проект не найден' } },
      [`POST ${SHARE}/accept`]: { body: { project_id: 'p1', role: 'editor' } },
    })
    const { router } = mount()
    expect(await screen.findByText('Закупка оборудования')).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Принять приглашение' }))

    await screen.findByText('Страница проекта')
    expect(router.state.location.pathname).toBe('/projects/p1')
    expect(toastSuccess).toHaveBeenCalledWith('Приглашение принято')
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1)
  })

  it('если доступ уже есть, вместо «принять» — «Открыть проект»', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: signedSession },
      [`GET ${SHARE}`]: { body: shared('editor') },
      'GET /api/v1/projects/p1': { body: { ...detail, access: 'editor' } },
    })
    mount()
    const open = await screen.findByRole('link', { name: 'Открыть проект' })
    expect(open).toHaveAttribute('href', '/projects/p1')
    expect(screen.queryByRole('button', { name: 'Принять приглашение' })).not.toBeInTheDocument()
  })

  it('ссылку отозвали, пока страница была открыта: приём падает и экран меняется', async () => {
    let revoked = false
    stubApi({
      'GET /api/v1/auth/session': { body: signedSession },
      [`GET ${SHARE}`]: () =>
        revoked
          ? { status: 404, body: { detail: 'Ссылка не найдена' } }
          : { body: shared('editor') },
      'GET /api/v1/projects/p1': { status: 404, body: { detail: 'Проект не найден' } },
      [`POST ${SHARE}/accept`]: () => {
        revoked = true
        return { status: 404, body: { detail: 'Ссылка не найдена' } }
      },
    })
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'Принять приглашение' }))
    expect(await screen.findByText('Ссылка недействительна')).toBeInTheDocument()
    expect(toastError).toHaveBeenCalled()
  })
})

describe('страница по ссылке: недоступные ссылки', () => {
  it.each([
    ['гость', guestSession],
    ['вошедший', signedSession],
  ])('404 для %s — «Ссылка недействительна»', async (_who, session) => {
    stubApi({
      'GET /api/v1/auth/session': { body: session },
      [`GET ${SHARE}`]: { status: 404, body: { detail: 'Ссылка не найдена' } },
    })
    mount()
    expect(await screen.findByText('Ссылка недействительна')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'К проектам' })).toBeInTheDocument()
  })

  it.each([
    ['гость', guestSession],
    ['вошедший', signedSession],
  ])('410 для %s — «Срок действия ссылки истёк»', async (_who, session) => {
    stubApi({
      'GET /api/v1/auth/session': { body: session },
      [`GET ${SHARE}`]: { status: 410, body: { detail: 'Срок ссылки истёк' } },
    })
    mount()
    expect(await screen.findByText('Срок действия ссылки истёк')).toBeInTheDocument()
  })

  it('сбой сервера — общая ошибка с повтором, без слова «токен»', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: guestSession },
      [`GET ${SHARE}`]: { status: 500, body: { detail: 'Внутренняя ошибка' } },
    })
    mount()
    expect(await screen.findByText('Не удалось открыть ссылку')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/токен/i)
  })
})
