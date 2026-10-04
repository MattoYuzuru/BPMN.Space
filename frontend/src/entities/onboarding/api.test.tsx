import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { sessionKeys } from '@/entities/session'
import { stubApi } from '@/test/api-stub'
import {
  fetchItemTarget,
  onboardingKeys,
  useOnboarding,
  useReportOnboardingEvent,
  useRestartTour,
  useSetChecklistHidden,
  useUpdateTour,
} from './api'
import type { OnboardingState, TourState } from './model'

const toastError = vi.fn()
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: (...args: unknown[]) => toastError(...args) }),
}))

const USER = { id: 'user-1', email: 'a@example.com' }

const TOUR: TourState = {
  status: 'pending',
  step: null,
  project_id: null,
  updated_at: '2026-10-04T10:00:00Z',
}

const base: OnboardingState = {
  enabled: true,
  tour: TOUR,
  checklist: { hidden: false, items: [] },
  tour_text_suggestion: 'Текст',
}

function setup(state?: OnboardingState, user: typeof USER | null = USER) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(sessionKeys.all, { auth_enabled: true, user })
  if (state) client.setQueryData(onboardingKeys.user(user?.id), state)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

afterEach(() => {
  vi.unstubAllGlobals()
  toastError.mockReset()
})

describe('useOnboarding', () => {
  it('ключ включает id пользователя, а данные приходят с сервера', async () => {
    const calls = stubApi({ 'GET /api/v1/me/onboarding': { body: base } })
    const { client, wrapper } = setup()
    const { result } = renderHook(() => useOnboarding(), { wrapper })
    await waitFor(() => expect(result.current.data).toEqual(base))
    expect(client.getQueryData(onboardingKeys.user('user-1'))).toEqual(base)
    expect(client.getQueryData(onboardingKeys.user('user-2'))).toBeUndefined()
    expect(calls).toHaveLength(1)
  })

  it('свежие данные (30 с) повторно не запрашиваются', async () => {
    const calls = stubApi({ 'GET /api/v1/me/onboarding': { body: base } })
    const { wrapper } = setup(base)
    const { result } = renderHook(() => useOnboarding(), { wrapper })
    await waitFor(() => expect(result.current.data).toEqual(base))
    expect(calls).toHaveLength(0)
  })

  it('гостю запрос не уходит', async () => {
    const calls = stubApi({ 'GET /api/v1/me/onboarding': { body: base } })
    const { wrapper } = setup(undefined, null)
    const { result } = renderHook(() => useOnboarding(), { wrapper })
    await act(async () => {})
    expect(result.current.data).toBeUndefined()
    expect(calls).toHaveLength(0)
  })

  it('у разных пользователей разные ключи', () => {
    expect(onboardingKeys.user('a')).not.toEqual(onboardingKeys.user('b'))
    expect(onboardingKeys.user(undefined)).toEqual(['onboarding', 'guest'])
  })
})

describe('useUpdateTour', () => {
  it('отправляет изменение и кладёт ответ сервера в кэш', async () => {
    const next: OnboardingState = {
      ...base,
      tour: { ...TOUR, status: 'active', step: 'project.create' },
    }
    const calls = stubApi({ 'PATCH /api/v1/me/onboarding/tour': { body: next } })
    const { client, wrapper } = setup(base)
    const { result } = renderHook(() => useUpdateTour(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ status: 'active' })
    })
    expect(calls[0]?.body).toEqual({ status: 'active' })
    expect(client.getQueryData(onboardingKeys.user('user-1'))).toEqual(next)
  })

  it('при конфликте перечитывает состояние', async () => {
    const fresh: OnboardingState = {
      ...base,
      tour: { ...TOUR, status: 'dismissed' },
    }
    const calls = stubApi({
      'PATCH /api/v1/me/onboarding/tour': { status: 409, body: { detail: 'Нельзя' } },
      'GET /api/v1/me/onboarding': { body: fresh },
    })
    const { client, wrapper } = setup(base)
    renderHook(() => useOnboarding(), { wrapper }) // наблюдатель: перечитываются только активные запросы
    const { result } = renderHook(() => useUpdateTour(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ status: 'active' }).catch(() => undefined)
    })
    await waitFor(() => expect(client.getQueryData(onboardingKeys.user('user-1'))).toEqual(fresh))
    expect(calls.map((call) => call.method)).toEqual(['PATCH', 'GET'])
  })
})

describe('useRestartTour', () => {
  it('перезапускает тур и обновляет кэш', async () => {
    const next: OnboardingState = {
      ...base,
      tour: { ...TOUR, status: 'active', step: 'project.create' },
    }
    stubApi({ 'POST /api/v1/me/onboarding/tour/restart': { body: next } })
    const { client, wrapper } = setup(base)
    const { result } = renderHook(() => useRestartTour(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync()
    })
    expect(client.getQueryData(onboardingKeys.user('user-1'))).toEqual(next)
  })

  it('ошибка — уведомление', async () => {
    stubApi({
      'POST /api/v1/me/onboarding/tour/restart': { status: 500, body: { detail: 'Сбой' } },
    })
    const { wrapper } = setup(base)
    const { result } = renderHook(() => useRestartTour(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync().catch(() => undefined)
    })
    expect(toastError).toHaveBeenCalledWith('Не удалось запустить обучение', {
      description: 'Сбой',
    })
  })
})

describe('useSetChecklistHidden', () => {
  it('скрывает плашку сразу, при ошибке возвращает и сообщает', async () => {
    stubApi({
      'PATCH /api/v1/me/onboarding/checklist': { status: 500, body: { detail: 'Сбой' } },
    })
    const { client, wrapper } = setup(base)
    const { result } = renderHook(() => useSetChecklistHidden(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync(true).catch(() => undefined)
    })
    const state = client.getQueryData<OnboardingState>(onboardingKeys.user('user-1'))
    expect(state?.checklist?.hidden).toBe(false)
    expect(toastError).toHaveBeenCalled()
  })

  it('успех — ответ сервера в кэше', async () => {
    const hidden: OnboardingState = { ...base, checklist: { hidden: true, items: [] } }
    const calls = stubApi({ 'PATCH /api/v1/me/onboarding/checklist': { body: hidden } })
    const { client, wrapper } = setup(base)
    const { result } = renderHook(() => useSetChecklistHidden(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync(true)
    })
    expect(calls[0]?.body).toEqual({ hidden: true })
    expect(client.getQueryData(onboardingKeys.user('user-1'))).toEqual(hidden)
  })
})

describe('useReportOnboardingEvent', () => {
  it('не шлёт, если пункт уже отмечен в кэше', async () => {
    const marked: OnboardingState = {
      ...base,
      checklist: {
        hidden: false,
        items: [{ key: 'simulation_run', completed_at: '2026-10-04T10:00:00Z', source: 'client' }],
      },
    }
    const calls = stubApi({ 'POST /api/v1/me/onboarding/events': { status: 204 } })
    const { wrapper } = setup(marked)
    const { result } = renderHook(() => useReportOnboardingEvent(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync('simulation_run')
    })
    expect(calls).toHaveLength(0)
  })

  it('шлёт отметку и сразу показывает пункт выполненным', async () => {
    const synced: OnboardingState = {
      ...base,
      checklist: {
        hidden: false,
        items: [
          { key: 'diagram_exported', completed_at: '2026-10-04T11:00:00Z', source: 'client' },
        ],
      },
    }
    const calls = stubApi({
      'POST /api/v1/me/onboarding/events': { status: 204 },
      'GET /api/v1/me/onboarding': { body: synced },
    })
    const { client, wrapper } = setup(base)
    const { result } = renderHook(() => useReportOnboardingEvent(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync('diagram_exported')
    })
    expect(calls[0]).toMatchObject({
      method: 'POST',
      path: '/api/v1/me/onboarding/events',
      body: { item: 'diagram_exported' },
    })
    await waitFor(() =>
      expect(
        client
          .getQueryData<OnboardingState>(onboardingKeys.user('user-1'))
          ?.checklist?.items.map((item) => item.key),
      ).toEqual(['diagram_exported']),
    )
  })

  it('второй вызов, пока первый в пути, не дублирует запрос', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const request = input as Request
        const path = new URL(request.url).pathname
        if (path.endsWith('/auth/csrf')) {
          return Response.json({ csrf_token: 'csrf-test-token' })
        }
        if (request.method === 'POST') {
          calls.push(path)
          await gate
          return new Response(null, { status: 204 })
        }
        return Response.json(base)
      }),
    )
    const { wrapper } = setup(base)
    const { result } = renderHook(() => useReportOnboardingEvent(), { wrapper })
    let first: Promise<unknown> = Promise.resolve()
    let second: Promise<unknown> = Promise.resolve()
    act(() => {
      first = result.current.mutateAsync('simulation_run')
      second = result.current.mutateAsync('simulation_run')
    })
    await waitFor(() => expect(calls).toHaveLength(1))
    release()
    await act(async () => {
      await Promise.all([first, second])
    })
    expect(calls).toHaveLength(1)
  })

  it('кэш ещё не загружен: сначала дожидается состояния, потом шлёт отметку', async () => {
    const calls = stubApi({
      'GET /api/v1/me/onboarding': { body: base },
      'POST /api/v1/me/onboarding/events': { status: 204 },
    })
    const { client, wrapper } = setup()
    const { result } = renderHook(() => useReportOnboardingEvent(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync('simulation_run')
    })
    expect(calls.map((call) => `${call.method} ${call.path}`).slice(0, 2)).toEqual([
      'GET /api/v1/me/onboarding',
      'POST /api/v1/me/onboarding/events',
    ])
    expect(client.getQueryData(onboardingKeys.user('user-1'))).toBeDefined()
  })

  it('кэш не загружен и уже отмечено на сервере: запроса отметки нет', async () => {
    const marked: OnboardingState = {
      ...base,
      checklist: {
        hidden: false,
        items: [{ key: 'simulation_run', completed_at: '2026-10-04T10:00:00Z', source: 'client' }],
      },
    }
    const calls = stubApi({
      'GET /api/v1/me/onboarding': { body: marked },
      'POST /api/v1/me/onboarding/events': { status: 204 },
    })
    const { wrapper } = setup()
    const { result } = renderHook(() => useReportOnboardingEvent(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync('simulation_run')
    })
    expect(calls.map((call) => call.method)).toEqual(['GET'])
  })

  it('при выключенном онбординге и при сбое загрузки состояния отметка не уходит', async () => {
    const calls = stubApi({ 'POST /api/v1/me/onboarding/events': { status: 204 } })
    for (const initial of [{ enabled: false } as OnboardingState, undefined]) {
      const { wrapper } = setup(initial)
      const { result } = renderHook(() => useReportOnboardingEvent(), { wrapper })
      await act(async () => {
        await result.current.mutateAsync('simulation_run')
      })
    }
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0)
  })

  it('ошибка отправки не показывает уведомление и не отмечает пункт', async () => {
    stubApi({
      'POST /api/v1/me/onboarding/events': { status: 500, body: { detail: 'Сбой' } },
    })
    const { client, wrapper } = setup(base)
    const { result } = renderHook(() => useReportOnboardingEvent(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync('simulation_run').catch(() => undefined)
    })
    expect(toastError).not.toHaveBeenCalled()
    expect(
      client.getQueryData<OnboardingState>(onboardingKeys.user('user-1'))?.checklist?.items,
    ).toEqual([])
  })
})

describe('fetchItemTarget', () => {
  it('просит место по ключу пункта', async () => {
    const target = {
      route: 'workspace',
      project_id: 'p-1',
      question_id: 'q-1',
      hint: 'do_item',
    }
    const calls = stubApi({
      'GET /api/v1/me/onboarding/items/question_answered/target': { body: target },
    })
    await expect(fetchItemTarget('question_answered')).resolves.toEqual(target)
    expect(calls[0]?.path).toBe('/api/v1/me/onboarding/items/question_answered/target')
  })

  it('ошибка сервера — ApiError', async () => {
    stubApi({
      'GET /api/v1/me/onboarding/items/project_shared/target': {
        status: 404,
        body: { detail: 'Обучение отключено' },
      },
    })
    await expect(fetchItemTarget('project_shared')).rejects.toMatchObject({ status: 404 })
  })
})
