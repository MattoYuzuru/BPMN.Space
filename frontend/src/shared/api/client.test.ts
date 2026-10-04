import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { stubUploads } from '@/test/xhr'
import { ApiError, errorMessage, postForm, resetCsrfToken, unwrap } from './client'

describe('postForm', () => {
  beforeEach(resetCsrfToken)
  afterEach(() => vi.unstubAllGlobals())

  it('один раз повторяет запрос с новым токеном, если прежний отклонён', async () => {
    const { requests } = stubUploads([
      { status: 403, body: { detail: 'CSRF-токен отсутствует или не совпадает' } },
      { body: { id: 'source-1' } },
    ])

    const result = await postForm('/api/v1/projects/p/sources/file', new FormData())

    expect(result).toEqual({ id: 'source-1' })
    expect(requests).toHaveLength(2)
    expect(requests[0]?.headers.get('X-CSRF-Token')).not.toBe(
      requests[1]?.headers.get('X-CSRF-Token'),
    )
  })

  it('не повторяет запрос при 403 по другой причине', async () => {
    const { requests } = stubUploads([{ status: 403, body: { detail: 'Нет прав на проект' } }])

    await expect(postForm('/x', new FormData())).rejects.toMatchObject({
      status: 403,
      message: 'Нет прав на проект',
    })
    expect(requests).toHaveLength(1)
  })

  it('повторяет только один раз', async () => {
    const csrf = { status: 403, body: { detail: 'CSRF-токен не совпадает' } }
    const { requests } = stubUploads([csrf, csrf, csrf])

    await expect(postForm('/x', new FormData())).rejects.toBeInstanceOf(ApiError)
    expect(requests).toHaveLength(2)
  })

  it('не стартует, если signal уже отменён', async () => {
    const { requests, csrfCalls } = stubUploads([{ body: {} }])
    const controller = new AbortController()
    controller.abort()

    await expect(
      postForm('/x', new FormData(), { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' })
    expect(requests).toHaveLength(0)
    expect(csrfCalls()).toBe(0)
  })

  it('читает код ошибки и паузу до повтора из ответа 429', async () => {
    stubUploads([{ status: 429, body: { detail: 'Too many' }, headers: { 'Retry-After': '30' } }])

    const error = await postForm('/x', new FormData()).catch((reason: unknown) => reason)

    expect(error).toMatchObject({ status: 429, retryAfter: 30 })
    expect(errorMessage(error)).toContain('Слишком много')
  })
})

describe('unwrap', () => {
  const response = (status: number, headers: Record<string, string> = {}) =>
    new Response(null, { status, headers })

  it('берёт код из строкового detail и не показывает его как текст', () => {
    try {
      unwrap({ error: { detail: 'LOGIN_BAD_CREDENTIALS' }, response: response(400) })
      expect.unreachable()
    } catch (error) {
      expect(error).toMatchObject({ status: 400, code: 'LOGIN_BAD_CREDENTIALS' })
      expect((error as ApiError).message).toBe('Ошибка сервера (400)')
    }
  })

  it('берёт код из объекта detail', () => {
    try {
      unwrap({
        error: { detail: { code: 'REGISTER_INVALID_PASSWORD', reason: 'short' } },
        response: response(400),
      })
      expect.unreachable()
    } catch (error) {
      expect(error).toMatchObject({ code: 'REGISTER_INVALID_PASSWORD' })
    }
  })

  it('оставляет русский текст сервера как сообщение', () => {
    try {
      unwrap({ error: { detail: 'Проект не найден' }, response: response(404) })
      expect.unreachable()
    } catch (error) {
      expect((error as ApiError).message).toBe('Проект не найден')
    }
  })

  it('передаёт Retry-After', () => {
    try {
      unwrap({ error: {}, response: response(429, { 'Retry-After': '12' }) })
      expect.unreachable()
    } catch (error) {
      expect((error as ApiError).retryAfter).toBe(12)
    }
  })
})
