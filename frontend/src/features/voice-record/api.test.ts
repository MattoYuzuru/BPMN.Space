import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, resetCsrfToken } from '@/shared/api/client'
import { stubUploads } from '@/test/xhr'
import { NO_SPEECH_MESSAGE, transcribeAudio } from './api'

describe('голосовая расшифровка', () => {
  beforeEach(resetCsrfToken)
  afterEach(() => vi.unstubAllGlobals())

  it('отправляет аудио на сервер с CSRF-токеном и cookie', async () => {
    const { requests } = stubUploads([
      { body: { text: 'Оператор проверяет заявку.', duration_sec: 3, language: 'ru-RU' } },
    ])

    const result = await transcribeAudio(new Blob(['audio-bytes'], { type: 'audio/webm' }))

    expect(result.text).toBe('Оператор проверяет заявку.')
    const [request] = requests
    expect(request?.method).toBe('POST')
    expect(request?.url).toBe('/api/v1/transcriptions')
    expect(request?.withCredentials).toBe(true)
    expect(request?.headers.get('X-CSRF-Token')).toMatch(/^csrf-/)
    expect(request?.body?.get('file')).toBeInstanceOf(File)
  })

  it('называет файл по формату записи: ogg для Firefox, webm для остальных', async () => {
    const { requests } = stubUploads([
      { body: { text: 'раз', duration_sec: 1, language: 'ru-RU' } },
      { body: { text: 'два', duration_sec: 1, language: 'ru-RU' } },
    ])

    await transcribeAudio(new Blob(['a'], { type: 'audio/ogg;codecs=opus' }))
    await transcribeAudio(new Blob(['a'], { type: 'audio/webm' }))

    expect((requests[0]?.body?.get('file') as File | null)?.name).toBe('voice.ogg')
    expect((requests[1]?.body?.get('file') as File | null)?.name).toBe('voice.webm')
  })

  it('не принимает пустую расшифровку', async () => {
    stubUploads([{ body: { text: '  ', duration_sec: 1, language: 'ru-RU' } }])

    await expect(transcribeAudio(new Blob(['audio']))).rejects.toEqual(
      new ApiError(422, NO_SPEECH_MESSAGE, { code: 'NO_SPEECH' }),
    )
  })
})
