import { type ReactNode, useCallback, useEffect, useSyncExternalStore } from 'react'
import {
  getThemeState,
  type ResolvedTheme,
  setThemePreference,
  startThemeSync,
  subscribeTheme,
  type ThemePreference,
} from './theme-store'

export interface UseTheme {
  /** Выбор пользователя: светлая, тёмная или как в системе. */
  preference: ThemePreference
  /** Фактическая тема на экране. */
  resolved: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
  /** Переключить светлую и тёмную (для горячей клавиши). */
  toggle: () => void
}

export function useTheme(): UseTheme {
  const state = useSyncExternalStore(subscribeTheme, getThemeState, getThemeState)
  const setPreference = useCallback((preference: ThemePreference) => {
    setThemePreference(preference)
  }, [])
  const toggle = useCallback(() => {
    setThemePreference(getThemeState().resolved === 'dark' ? 'light' : 'dark')
  }, [])
  return { preference: state.preference, resolved: state.resolved, setPreference, toggle }
}

/** Подключает синхронизацию темы с системой и соседними вкладками. Ставится один раз в корне. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => startThemeSync(), [])
  return children
}
