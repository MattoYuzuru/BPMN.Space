import { afterEach, describe, expect, it, vi } from 'vitest'
import { transcribeAudio } from './voice-transcription'

describe('голосовая расшифровка через backend', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('отправляет аудио на backend без передачи ключа провайдера браузеру', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        text: 'Оператор проверяет заявку.',
        duration_sec: 3,
        language: 'ru-RU',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await transcribeAudio(new Blob(['audio-bytes'], { type: 'audio/webm' }))

    expect(result.text).toBe('Оператор проверяет заявку.')
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/transcriptions')
    expect(options.method).toBe('POST')
    expect(options.headers).toBeUndefined()
    expect(options.body).toBeInstanceOf(FormData)
    expect((options.body as FormData).get('file')).toBeInstanceOf(File)
  })

  it('не принимает пустой ответ от backend', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ text: '  ', duration_sec: 1, language: 'ru-RU' }),
      }),
    )

    await expect(transcribeAudio(new Blob(['audio']))).rejects.toThrow('пустую расшифровку')
  })
})
