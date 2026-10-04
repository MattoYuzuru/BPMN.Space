import { ApiError } from '@/shared/api/client'
import {
  activeLinks,
  defaultExpiryDays,
  expiryForRole,
  expiryOptions,
  linkState,
  type SharedProject,
  type ShareLink,
  sharePageState,
  shareUrl,
} from './model'

const NOW = new Date('2026-10-04T12:00:00Z')
const link = (patch: Partial<ShareLink> = {}): ShareLink => ({
  id: 'l1',
  role: 'viewer',
  created_at: '2026-10-01T10:00:00Z',
  expires_at: '2026-10-31T10:00:00Z',
  revoked_at: null,
  ...patch,
})

describe('сроки по ролям', () => {
  it('приглашение редактора — до 30 дней, просмотр — до года', () => {
    const editor = expiryOptions('editor').map((option) => Number(option.value))
    const viewer = expiryOptions('viewer').map((option) => Number(option.value))
    expect(Math.max(...editor)).toBe(30)
    expect(Math.max(...viewer)).toBe(365)
  })

  it('сроки по умолчанию совпадают с серверными и входят в список', () => {
    expect(defaultExpiryDays('editor')).toBe(7)
    expect(defaultExpiryDays('viewer')).toBe(30)
    for (const role of ['viewer', 'editor'] as const) {
      expect(expiryOptions(role).map((option) => option.value)).toContain(
        String(defaultExpiryDays(role)),
      )
    }
  })

  it('при смене роли допустимый срок остаётся, недопустимый заменяется обычным', () => {
    expect(expiryForRole('editor', 7)).toBe(7)
    expect(expiryForRole('editor', 365)).toBe(7)
    expect(expiryForRole('viewer', 1)).toBe(30)
    expect(expiryForRole('viewer', 90)).toBe(90)
  })
})

describe('shareUrl', () => {
  it('склеивает origin и путь, не задваивая слэш', () => {
    expect(shareUrl('https://arch.example', '/share/abc')).toBe('https://arch.example/share/abc')
    expect(shareUrl('https://arch.example/', '/share/abc')).toBe('https://arch.example/share/abc')
  })
})

describe('состояние и список ссылок', () => {
  it('отозванная и истёкшая ссылки не действуют', () => {
    expect(linkState(link(), NOW)).toBe('active')
    expect(linkState(link({ revoked_at: '2026-10-02T00:00:00Z' }), NOW)).toBe('revoked')
    expect(linkState(link({ expires_at: '2026-10-03T00:00:00Z' }), NOW)).toBe('expired')
  })

  it('в списке остаются только действующие, новые первыми', () => {
    const list = [
      link({ id: 'old', created_at: '2026-09-20T00:00:00Z' }),
      link({ id: 'gone', revoked_at: '2026-10-02T00:00:00Z' }),
      link({ id: 'new', created_at: '2026-10-03T00:00:00Z' }),
      link({ id: 'late', expires_at: '2026-10-01T00:00:00Z' }),
    ]
    expect(activeLinks(list, NOW).map((item) => item.id)).toEqual(['new', 'old'])
  })
})

describe('sharePageState', () => {
  const shared = (role: 'viewer' | 'editor') =>
    ({ role, editor_requires_account: role === 'editor', detail: { id: 'p1' } }) as SharedProject
  const failure = (status: number) => ({
    status: 'error' as const,
    error: new ApiError(status, 'x'),
  })

  it('пока ответа нет — загрузка', () => {
    expect(sharePageState({ status: 'pending' })).toEqual({ kind: 'loading' })
  })

  it('ссылка на просмотр открывается и гостю, и вошедшему', () => {
    const result = sharePageState({ status: 'success', data: shared('viewer') })
    expect(result.kind).toBe('viewer')
  })

  it('приглашение редактора: вошедший получает карточку принятия, гость — вход (401)', () => {
    expect(sharePageState({ status: 'success', data: shared('editor') }).kind).toBe('invite')
    expect(sharePageState(failure(401))).toEqual({ kind: 'sign-in' })
  })

  it('404 — недействительна, 410 — срок истёк, для любой роли', () => {
    expect(sharePageState(failure(404))).toEqual({ kind: 'invalid' })
    expect(sharePageState(failure(410))).toEqual({ kind: 'expired' })
  })

  it('прочие ошибки и обрыв связи — общий сбой с повтором', () => {
    expect(sharePageState(failure(500)).kind).toBe('failed')
    expect(sharePageState({ status: 'error', error: new TypeError('network') }).kind).toBe('failed')
  })
})
