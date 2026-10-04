import { useMutation } from '@tanstack/react-query'
import { ApiError, postForm, type Schemas } from '@/shared/api/client'

export type Transcription = Schemas['Transcription']

/** Расширение файла по типу записи: Firefox пишет ogg, Chromium — webm. */
function audioFileName(blob: Blob): string {
  return `voice.${blob.type.includes('ogg') ? 'ogg' : 'webm'}`
}

/** Отправляет запись на распознавание (`POST /transcriptions`); ключ провайдера остаётся на сервере. */
export async function transcribeAudio(blob: Blob): Promise<Transcription> {
  const form = new FormData()
  form.append('file', blob, audioFileName(blob))
  const result = await postForm<Transcription>('/api/v1/transcriptions', form)
  if (!result.text?.trim()) throw new ApiError(422, 'Запишите ещё раз.')
  return result
}

/** Распознавание записи как мутация: состояние ожидания и ошибки — для экрана записи. */
export function useTranscribe() {
  return useMutation({ mutationFn: transcribeAudio })
}
