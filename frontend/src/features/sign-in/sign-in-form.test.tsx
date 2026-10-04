import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { AuthMode } from '@/entities/session'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { SignInForm } from './sign-in-form'

const toastSuccess = vi.fn()
const toastDefault = vi.fn()
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign((...args: unknown[]) => toastDefault(...args), {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: vi.fn(),
  }),
}))

function Harness({ initial = 'login' }: { initial?: AuthMode }) {
  const [mode, setMode] = useState<AuthMode>(initial)
  return <SignInForm mode={mode} onModeChange={setMode} redirectTo="/" />
}

async function mount(initial: AuthMode = 'login') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const root = createRootRoute({ component: () => <Harness initial={initial} /> })
  const router = createRouter({
    routeTree: root.addChildren([createRoute({ getParentRoute: () => root, path: '/' })]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  await screen.findByRole('radio', { name: 'Регистрация' })
  return { user }
}

const passwordField = () => screen.getByLabelText('Пароль', { exact: true }) as HTMLInputElement
const keyButton = () => screen.queryByRole('button', { name: 'Сгенерировать надёжный пароль' })

afterEach(() => {
  vi.unstubAllGlobals()
  toastSuccess.mockReset()
  toastDefault.mockReset()
})

describe('SignInForm: разметка для менеджеров паролей', () => {
  it('вход: current-password, имена полей, без правил Safari и без кнопки-ключа', async () => {
    await mount('login')
    expect(passwordField()).toHaveAttribute('autocomplete', 'current-password')
    expect(passwordField()).toHaveAttribute('name', 'password')
    expect(passwordField()).not.toHaveAttribute('passwordrules')
    expect(screen.getByLabelText('Почта')).toHaveAttribute('name', 'email')
    expect(screen.getByLabelText('Почта')).toHaveAttribute('autocomplete', 'username')
    expect(keyButton()).toBeNull()
  })

  it('регистрация: new-password, passwordrules для Safari и кнопка-ключ', async () => {
    await mount('register')
    expect(passwordField()).toHaveAttribute('autocomplete', 'new-password')
    expect(passwordField().getAttribute('passwordrules')).toMatch(
      /minlength: 12; maxlength: 128; required: lower; required: upper; required: digit;/,
    )
    expect(keyButton()).toBeInTheDocument()
  })

  it('при смене режима поле пароля пересоздаётся, а не меняет атрибут у того же элемента', async () => {
    const { user } = await mount('login')
    const before = passwordField()
    await user.click(screen.getByRole('radio', { name: 'Регистрация' }))
    const after = passwordField()
    expect(after).not.toBe(before)
    expect(before.isConnected).toBe(false)
    expect(after).toHaveAttribute('autocomplete', 'new-password')
    expect(keyButton()).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: 'Вход' }))
    expect(keyButton()).toBeNull()
    expect(passwordField()).toHaveAttribute('autocomplete', 'current-password')
  })

  it('id полей не заданы вручную: подпись связана через Field', async () => {
    await mount('register')
    expect(passwordField().id).not.toBe('password')
    expect(passwordField().id).not.toBe('')
  })
})

describe('SignInForm: генерация пароля', () => {
  it('клик подставляет пароль из 20 символов, показывает его и копирует в буфер', async () => {
    const { user } = await mount('register')
    const write = vi.spyOn(navigator.clipboard, 'writeText')
    expect(passwordField()).toHaveAttribute('type', 'password')

    await user.click(keyButton() as HTMLElement)

    expect(passwordField()).toHaveAttribute('type', 'text')
    expect(passwordField().value).toHaveLength(20)
    expect(write).toHaveBeenCalledWith(passwordField().value)
    expect(passwordField()).toHaveFocus()
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith('Пароль скопирован', {
        description: 'Сохраните его в менеджере паролей',
      }),
    )
  })

  it('повторный клик даёт новый пароль', async () => {
    const { user } = await mount('register')
    await user.click(keyButton() as HTMLElement)
    const first = passwordField().value
    await user.click(keyButton() as HTMLElement)
    expect(passwordField().value).toHaveLength(20)
    expect(passwordField().value).not.toBe(first)
  })

  it('сбрасывает ошибку поля пароля', async () => {
    const { user } = await mount('register')
    await user.click(screen.getByRole('button', { name: 'Создать аккаунт' }))
    expect(await screen.findByText('Введите пароль')).toBeInTheDocument()
    await user.click(keyButton() as HTMLElement)
    expect(screen.queryByText('Введите пароль')).toBeNull()
  })

  it('если буфер недоступен, пароль всё равно в поле и показано спокойное уведомление', async () => {
    const { user } = await mount('register')
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('denied'))
    await user.click(keyButton() as HTMLElement)
    expect(passwordField().value).toHaveLength(20)
    await waitFor(() =>
      expect(toastDefault).toHaveBeenCalledWith('Пароль создан', {
        description: 'Скопируйте его из поля',
      }),
    )
    expect(toastSuccess).not.toHaveBeenCalled()
  })

  it('перед отправкой поле снова становится type="password", а пароль уходит как есть', async () => {
    const calls = stubApi({
      'POST /api/v1/auth/register': { status: 201, body: { id: 'u1', email: 'a@b.ru' } },
      'POST /api/v1/auth/session/login': { status: 204 },
    })
    const { user } = await mount('register')
    await user.type(screen.getByLabelText('Почта'), 'anna@company.ru')
    await user.click(keyButton() as HTMLElement)
    const generated = passwordField().value
    expect(passwordField()).toHaveAttribute('type', 'text')

    // Слушатель на document срабатывает после обработчика React: flushSync уже скрыл пароль.
    let typeAtSubmit: string | null = null
    const onSubmit = () => {
      typeAtSubmit = passwordField().getAttribute('type')
    }
    document.addEventListener('submit', onSubmit)
    await user.click(screen.getByRole('button', { name: 'Создать аккаунт' }))

    expect(passwordField()).toHaveAttribute('type', 'password')
    document.removeEventListener('submit', onSubmit)
    expect(typeAtSubmit).toBe('password')
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/api/v1/auth/register')?.body).toEqual({
        email: 'anna@company.ru',
        password: generated,
      }),
    )
  })

  it('смена режима прячет пароль', async () => {
    const { user } = await mount('register')
    await user.click(keyButton() as HTMLElement)
    expect(passwordField()).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('radio', { name: 'Вход' }))
    expect(passwordField()).toHaveAttribute('type', 'password')
  })
})
