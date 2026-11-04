import { useCallback, useState } from 'react'
import { isAcceptedFile, isMediaFile, useAddFileSource } from '@/entities/source'
import { toast } from '@/shared/ui'

export interface UploadItem {
  id: string
  name: string
  progress: number
}

/**
 * Очередь загрузок файлов с ходом каждой. Неподдерживаемые форматы отсекаются сразу,
 * без запроса: пользователь видит, какие файлы и почему не приняты.
 */
export function useFileUploads(projectId: string) {
  const add = useAddFileSource(projectId)
  const [uploads, setUploads] = useState<UploadItem[]>([])
  // Записи сначала спрашивают профиль обработки; документы загружаются сразу.
  const [pendingMedia, setPendingMedia] = useState<File[] | null>(null)

  const send = useCallback(
    (files: File[], mediaProfile?: 'audio' | 'sparse' | 'detailed') => {
      for (const file of files) {
        const id = `${file.name}-${file.size}-${Date.now()}`
        setUploads((list) => [...list, { id, name: file.name, progress: 0 }])
        add.mutate(
          {
            file,
            mediaProfile,
            onProgress: (progress) =>
              setUploads((list) =>
                list.map((item) => (item.id === id ? { ...item, progress } : item)),
              ),
          },
          { onSettled: () => setUploads((list) => list.filter((item) => item.id !== id)) },
        )
      }
    },
    [add],
  )

  const upload = useCallback(
    (files: File[]) => {
      const rejected = files.filter((file) => !isAcceptedFile(file.name))
      if (rejected.length) {
        toast.error('Формат не поддерживается', {
          description: `${rejected.map((file) => file.name).join(', ')}. Подойдут документы (.txt, .md, .csv, .docx, .xlsx, .pptx, .pdf), аудио и видео.`,
        })
      }
      const accepted = files.filter((item) => isAcceptedFile(item.name))
      const media = accepted.filter((file) => isMediaFile(file.name))
      const documents = accepted.filter((file) => !isMediaFile(file.name))
      if (documents.length > 0) send(documents)
      if (media.length > 0) setPendingMedia(media)
    },
    [send],
  )

  const confirmMedia = useCallback(
    (profile: 'audio' | 'sparse' | 'detailed') => {
      if (pendingMedia) send(pendingMedia, profile)
      setPendingMedia(null)
    },
    [pendingMedia, send],
  )

  const cancelMedia = useCallback(() => setPendingMedia(null), [])

  return { uploads, upload, pendingMedia, confirmMedia, cancelMedia }
}
