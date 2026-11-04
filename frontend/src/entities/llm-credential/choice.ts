import { create } from 'zustand'
import type { ModelChoice } from './model'

const STORAGE_PREFIX = 'arkhitektor:model-choice:'

function read(userId: string): ModelChoice | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + userId)
    if (!raw) return null
    const value: unknown = JSON.parse(raw)
    if (
      value &&
      typeof value === 'object' &&
      typeof (value as ModelChoice).credentialId === 'string' &&
      typeof (value as ModelChoice).model === 'string'
    ) {
      return value as ModelChoice
    }
  } catch {
    // Хранилище недоступно или повреждено — просто нет запомненного выбора.
  }
  return null
}

function write(userId: string, choice: ModelChoice | null) {
  try {
    if (choice) window.localStorage.setItem(STORAGE_PREFIX + userId, JSON.stringify(choice))
    else window.localStorage.removeItem(STORAGE_PREFIX + userId)
  } catch {
    // Без хранилища выбор живёт до перезагрузки страницы.
  }
}

interface ChoiceStore {
  /** Выбор по пользователям: у каждого аккаунта на устройстве свой. */
  choices: Record<string, ModelChoice | null>
  set: (userId: string, choice: ModelChoice | null) => void
  /** Забыть выбор, если он указывает на удалённый ключ. */
  forget: (credentialId: string) => void
}

export const useModelChoiceStore = create<ChoiceStore>((set, get) => ({
  choices: {},
  set: (userId, choice) => {
    write(userId, choice)
    set((state) => ({ choices: { ...state.choices, [userId]: choice } }))
  },
  forget: (credentialId) => {
    for (const [userId, choice] of Object.entries(get().choices)) {
      if (choice?.credentialId === credentialId) get().set(userId, null)
    }
  },
}))

/** Запомненный выбор пользователя (из памяти, иначе из localStorage). */
export function getModelChoice(userId: string | undefined): ModelChoice | null {
  if (!userId) return null
  const cached = useModelChoiceStore.getState().choices[userId]
  if (cached !== undefined) return cached
  const stored = read(userId)
  useModelChoiceStore.setState((state) => ({ choices: { ...state.choices, [userId]: stored } }))
  return stored
}
