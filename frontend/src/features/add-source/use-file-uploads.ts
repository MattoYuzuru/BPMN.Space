import { useCallback, useState } from 'react'
import { isAcceptedFile, useAddFileSource } from '@/entities/source'
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

  const upload = useCallback(
    (files: File[]) => {
      const rejected = files.filter((file) => !isAcceptedFile(file.name))
      if (rejected.length) {
        toast.error('Формат не поддерживается', {
          description: `${rejected.map((file) => file.name).join(', ')}. Подойдут .txt, .md, .csv, .docx и .pdf.`,
        })
      }
      for (const file of files.filter((item) => isAcceptedFile(item.name))) {
        const id = `${file.name}-${file.size}-${Date.now()}`
        setUploads((list) => [...list, { id, name: file.name, progress: 0 }])
        add.mutate(
          {
            file,
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

  return { uploads, upload }
}
