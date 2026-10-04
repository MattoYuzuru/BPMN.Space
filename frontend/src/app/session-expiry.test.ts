import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { handleUnauthorized } from './session-expiry'

function setup(options: { session: unknown; protectedScreen?: boolean }) {
  const client = new QueryClient()
  // Состояние входа читается обычным запросом: подменяем ответ сервера.
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(options.session), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
  client.setQueryData(['projects', 'list'], { stale: true })
  const toLogin = vi.fn().mockResolvedValue(undefined)
  const context = {
    client,
    isProtected: () => options.protectedScreen ?? true,
    currentHref: () => '/projects/p1?question=q1',
    toLogin,
  }
  return { client, toLogin, context }
}

describe('handleUnauthorized', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('гостя уводит на вход с возвратом на текущий адрес и забывает данные аккаунта', async () => {
    const { client, toLogin, context } = setup({ session: { auth_enabled: true, user: null } })

    await handleUnauthorized(context)

    expect(toLogin).toHaveBeenCalledWith({ redirect: '/projects/p1?question=q1' })
    expect(client.getQueryData(['projects', 'list'])).toBeUndefined()
  })

  it('если сессия на месте, никуда не уводит', async () => {
    const { toLogin, context } = setup({
      session: { auth_enabled: true, user: { id: 'u', email: 'a@b.ru' } },
    })

    await handleUnauthorized(context)

    expect(toLogin).not.toHaveBeenCalled()
  })

  it('на публичных экранах ничего не делает', async () => {
    const { toLogin, context } = setup({
      session: { auth_enabled: true, user: null },
      protectedScreen: false,
    })

    await handleUnauthorized(context)

    expect(toLogin).not.toHaveBeenCalled()
  })

  it('несколько 401 подряд дают один переход', async () => {
    const { toLogin, context } = setup({ session: { auth_enabled: true, user: null } })

    await Promise.all([
      handleUnauthorized(context),
      handleUnauthorized(context),
      handleUnauthorized(context),
    ])

    expect(toLogin).toHaveBeenCalledTimes(1)
  })
})
