import { afterEach, describe, expect, it, vi } from 'vitest'
import { transcribeAudio } from './voice-transcription'

describe('голосовая расшифровка через backend', () => {
  afterEach(() => vi.unstubAllGlobals())

  function stubUploadResponse(payload: unknown) {
    const request = {
      method: '',
      url: '',
      headers: new Map<string, string>(),
      body: undefined as FormData | undefined,
      onload: undefined as (() => void) | undefined,
      onerror: undefined as (() => void) | undefined,
      status: 200,
      response: payload,
      responseType: '',
      withCredentials: false,
      upload: { onprogress: undefined as ((event: ProgressEvent) => void) | undefined },
      open(method: string, url: string) {
        this.method = method
        this.url = url
      },
      setRequestHeader(name: string, value: string) {
        this.headers.set(name, value)
      },
      send(body: FormData) {
        this.body = body
        this.onload?.()
      },
      abort: vi.fn(),
    }
    class MockXMLHttpRequest {
      method = ''
      url = ''
      headers = request.headers
      body: FormData | undefined
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      status = 200
      response = payload
      responseType = ''
      private credentials = false
      upload = request.upload

      get withCredentials() {
        return this.credentials
      }

      set withCredentials(value: boolean) {
        this.credentials = request.withCredentials = value
      }

      open(method: string, url: string) {
        request.method = this.method = method
        request.url = this.url = url
      }

      setRequestHeader(name: string, value: string) {
        request.headers.set(name, value)
      }

      send(body: FormData) {
        request.body = body
        this.body = body
        this.onload?.()
      }
    }
    vi.stubGlobal('XMLHttpRequest', MockXMLHttpRequest)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ csrf_token: 'csrf-test-token' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    return request
  }

  it('отправляет аудио на backend без передачи ключа провайдера браузеру', async () => {
    const request = stubUploadResponse({
      text: 'Оператор проверяет заявку.',
      duration_sec: 3,
      language: 'ru-RU',
    })

    const result = await transcribeAudio(new Blob(['audio-bytes'], { type: 'audio/webm' }))

    expect(result.text).toBe('Оператор проверяет заявку.')
    expect(request.method).toBe('POST')
    expect(request.url).toBe('/api/v1/transcriptions')
    expect(request.withCredentials).toBe(true)
    expect(request.headers.get('X-CSRF-Token')).toBe('csrf-test-token')
    expect(request.body).toBeInstanceOf(FormData)
    expect(request.body?.get('file')).toBeInstanceOf(File)
  })

  it('не принимает пустой ответ от backend', async () => {
    stubUploadResponse({ text: '  ', duration_sec: 1, language: 'ru-RU' })

    await expect(transcribeAudio(new Blob(['audio']))).rejects.toThrow('пустую расшифровку')
  })
})
