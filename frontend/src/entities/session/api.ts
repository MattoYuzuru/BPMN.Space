import {
  type QueryClient,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api, type Schemas, unwrap } from '@/shared/api/client'
import type { Session } from './model'

export const sessionKeys = {
  all: ['session'] as const,
}

/** Состояние входа. Сервер всегда отвечает 200: «гость» — это `user: null`, а не ошибка. */
export const sessionQueryOptions = queryOptions({
  queryKey: sessionKeys.all,
  queryFn: async ({ signal }): Promise<Session> =>
    unwrap(await api.GET('/api/v1/auth/session', { signal })),
  staleTime: 60_000,
})

export function useSession() {
  return useQuery(sessionQueryOptions)
}

/** Данные текущей сессии; пока не загружены (или аккаунты выключены) — null. */
export function useCurrentUser() {
  return useQuery({ ...sessionQueryOptions, select: (session) => session.user }).data ?? null
}

/** Всё, что относится к прошлому пользователю, выбрасываем: проекты, версии, вопросы. */
export function dropAccountData(client: QueryClient) {
  client.removeQueries({ predicate: (query) => query.queryKey[0] !== sessionKeys.all[0] })
}

export interface Credentials {
  email: string
  password: string
}

async function login({ email, password }: Credentials) {
  unwrap(
    await api.POST('/api/v1/auth/session/login', {
      // Вход принимает форму `username`/`password`, а не JSON.
      body: { username: email, password } as Schemas['login'],
      bodySerializer: (body) => new URLSearchParams(body as unknown as Record<string, string>),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    }),
  )
}

/** Вход: после успеха прежние данные сбрасываются, сессия перечитывается. */
export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: login,
    onSuccess: async () => {
      dropAccountData(client)
      await client.fetchQuery({ ...sessionQueryOptions, staleTime: 0 })
    },
  })
}

/** Регистрация сразу входит в аккаунт: отдельного шага «теперь войдите» нет. */
export function useRegister() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (credentials: Credentials) => {
      unwrap(await api.POST('/api/v1/auth/register', { body: credentials }))
      await login(credentials)
    },
    onSuccess: async () => {
      dropAccountData(client)
      await client.fetchQuery({ ...sessionQueryOptions, staleTime: 0 })
    },
  })
}

/** Выход: данные аккаунта удаляются из памяти сразу, сессия становится гостевой. */
export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/v1/auth/session/logout')),
    // После выхода состояние онбординга перечитывать не нужно (это был бы 401).
    meta: { skipOnboarding: true },
    onSuccess: () => {
      dropAccountData(client)
      client.setQueryData<Session>(sessionKeys.all, (session) => ({
        auth_enabled: session?.auth_enabled ?? true,
        user: null,
      }))
    },
  })
}
