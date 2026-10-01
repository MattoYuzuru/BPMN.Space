export interface TranscriptionResult {
  text: string
  duration_sec: number
  language: string
}

/** Передаёт запись локальному backend; ключ провайдера остаётся на сервере. */
export async function transcribeAudio(blob: Blob): Promise<TranscriptionResult> {
  const form = new FormData()
  form.append('file', blob, 'voice-note.webm')
  const response = await fetch('/api/v1/transcriptions', { method: 'POST', body: form })
  if (!response.ok) throw new Error(`Не удалось расшифровать запись (${response.status})`)

  const result = (await response.json()) as TranscriptionResult
  if (!result.text?.trim()) throw new Error('Сервис вернул пустую расшифровку')
  return result
}
