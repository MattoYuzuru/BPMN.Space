import { useCallback, useEffect, useRef, useState } from 'react'
// Прямой импорт модуля, а не индекса: индекс дизайн-системы сам рендерит CopyField,
// который использует этот хук, — импорт из индекса замкнул бы цикл shared/ui → shared/hooks → shared/ui.
import { toast } from '../ui/toast/toast'

/**
 * Копирование в буфер с подтверждением: `copied` на пару секунд включает галочку на кнопке;
 * если браузер отказал, `toast.error` просит выделить текст вручную (`failureHint`).
 */
export function useCopy(successMessage: string, failureHint = 'Выделите текст и скопируйте сами.') {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        toast.success(successMessage)
        clearTimeout(timer.current)
        timer.current = setTimeout(() => setCopied(false), 2000)
      } catch {
        toast.error('Не удалось скопировать', { description: failureHint })
      }
    },
    [successMessage, failureHint],
  )
  return { copied, copy }
}
