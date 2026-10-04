import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { sessionKeys } from './api'
import { requireSession, skipLoginIfSignedIn } from './guard'
import type { Session } from './model'

function clientWith(session: Session) {
  const client = new QueryClient()
  client.setQueryData(sessionKeys.all, session)
  return client
}

const guest: Session = { auth_enabled: true, user: null }
const signedIn: Session = { auth_enabled: true, user: { id: 'u1', email: 'anna@company.ru' } }
const open: Session = { auth_enabled: false, user: null }

describe('requireSession', () => {
  it('гостя отправляет на вход с адресом возврата', async () => {
    await expect(
      requireSession(clientWith(guest), '/projects/p1?question=q2'),
    ).rejects.toMatchObject({
      options: { to: '/login', search: { redirect: '/projects/p1?question=q2' } },
    })
  })

  it('с главной адрес возврата не нужен', async () => {
    await expect(requireSession(clientWith(guest), '/')).rejects.toMatchObject({
      options: { to: '/login', search: {} },
    })
  })

  it('чужой адрес в возврат не попадает', async () => {
    await expect(requireSession(clientWith(guest), '//evil.example')).rejects.toMatchObject({
      options: { search: {} },
    })
  })

  it('вошедшего пропускает', async () => {
    await expect(requireSession(clientWith(signedIn), '/projects/p1')).resolves.toEqual(signedIn)
  })

  it('стенд без аккаунтов открыт всем', async () => {
    await expect(requireSession(clientWith(open), '/projects/p1')).resolves.toEqual(open)
  })
})

describe('skipLoginIfSignedIn', () => {
  it('гостю показывает вход', async () => {
    await expect(skipLoginIfSignedIn(clientWith(guest), undefined)).resolves.toBeUndefined()
  })

  it('вошедшего ведёт на адрес возврата', async () => {
    await expect(skipLoginIfSignedIn(clientWith(signedIn), '/projects/p1')).rejects.toMatchObject({
      options: { href: '/projects/p1' },
    })
  })

  it('без аккаунтов вход не нужен: на главную, а чужой адрес игнорируется', async () => {
    await expect(
      skipLoginIfSignedIn(clientWith(open), 'https://evil.example'),
    ).rejects.toMatchObject({ options: { href: '/' } })
  })
})
