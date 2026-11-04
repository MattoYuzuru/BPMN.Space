import { useCallback, useState } from 'react'
import { create } from 'zustand'
import {
  defaultExpiryDays,
  expiryForRole,
  expiryOptions,
  type ShareRole,
  shareUrl,
} from '@/entities/share'
import { useCopy as useSharedCopy } from '@/shared/hooks/use-copy'

/** Подсказка под выбором роли: что получит человек с такой ссылкой. */
export const ROLE_HINT: Record<ShareRole, string> = {
  viewer: 'Откроется без входа, только чтение.',
  editor: 'Нужен аккаунт. Можно править, но не удалять.',
  reviewer: 'Проверка коллеги: чтение выбранной дорожки и ответы на её вопросы.',
}

/**
 * Состояние формы новой ссылки: обе роли предлагают одинаковый набор сроков.
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

/** Копирование адреса ссылки: общий `useCopy` с текстами для ссылок. */
export function useCopy(successMessage = 'Ссылка скопирована') {
  return useSharedCopy(successMessage, 'Выделите адрес и скопируйте сам.')
}

interface ShareDialogControl {
  /** Растёт на каждую просьбу закрыть окно «Поделиться». */
  closeRequest: number
  requestClose: () => void
}

/** Нейтральная точка: попросить закрыть окно «Поделиться» снаружи (обучение после создания ссылки). */
export const useShareDialogControl = create<ShareDialogControl>((set) => ({
  closeRequest: 0,
  requestClose: () => set((state) => ({ closeRequest: state.closeRequest + 1 })),
}))
