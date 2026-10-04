import { postForm, type Schemas } from '@/shared/api/client'

export interface TranscriptionResult {
  text: string
  duration_sec: number
  language: string
}

/** Передаёт запись локальному backend; ключ провайдера остаётся на сервере. */
export async function transcribeAudio(blob: Blob): Promise<TranscriptionResult> {
  const form = new FormData()
  form.append('file', blob, 'voice-note.webm')
  const result = await postForm<Schemas['Transcription']>('/api/v1/transcriptions', form)
  if (!result.text?.trim()) throw new Error('Сервис вернул пустую расшифровку')
  return result
}
