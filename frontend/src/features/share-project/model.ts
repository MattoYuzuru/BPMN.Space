import { useCallback, useEffect, useRef, useState } from 'react'
import {
  defaultExpiryDays,
  expiryForRole,
  expiryOptions,
  type ShareRole,
  shareUrl,
} from '@/entities/share'
import { toast } from '@/shared/ui'

/** Подсказка под выбором роли: что получит человек с такой ссылкой. */
export const ROLE_HINT: Record<ShareRole, string> = {
  viewer: 'Откроется без входа, только чтение.',
  editor: 'Нужен аккаунт. Можно править, но не удалять.',
}

/**
 * Состояние формы новой ссылки: роль и срок. Срок зависит от роли — у приглашения редактора
 * он короче; при смене роли прежний срок остаётся, если он допустим, иначе берётся обычный.
 */
export function useShareForm() {
  const [role, setRoleState] = useState<ShareRole>('viewer')
  const [days, setDays] = useState(defaultExpiryDays('viewer'))
  const setRole = useCallback((next: ShareRole) => {
    setRoleState(next)
    setDays((current) => expiryForRole(next, current))
  }, [])
  return { role, days, setRole, setDays, expiryOptions: expiryOptions(role) }
}

/** Полный адрес по пути ссылки; origin берётся из окна. */
export function fullShareUrl(urlPath: string): string {
  return shareUrl(window.location.origin, urlPath)
}

/**
 * Копирование в буфер с подтверждением. `copied` на пару секунд включает галочку на кнопке;
 * если браузер отказал, подсказываем выделить адрес руками.
 */
export function useCopy(successMessage = 'Ссылка скопирована') {
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
        toast.error('Не удалось скопировать', { description: 'Выделите адрес и скопируйте сам.' })
      }
    },
    [successMessage],
  )
  return { copied, copy }
}
