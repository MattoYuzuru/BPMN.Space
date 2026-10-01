/**
 * Тема интерфейса. Источник правды — атрибут data-theme на <html>, выбор пользователя —
 * localStorage `arkhitektor.theme`. Первичная установка до отрисовки — inline-скрипт
 * в index.html (без мигания), дальше тему ведёт этот модуль.
 */

export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export interface ThemeState {
  preference: ThemePreference
  resolved: ResolvedTheme
}

export const THEME_STORAGE_KEY = 'arkhitektor.theme'
const DEFAULT_PREFERENCE: ThemePreference = 'light'
const DARK_QUERY = '(prefers-color-scheme: dark)'
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'
const FALLBACK_TRANSITION_MS = 360

const isPreference = (value: unknown): value is ThemePreference =>
  value === 'light' || value === 'dark' || value === 'system'

function readStoredPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY)
    return isPreference(value) ? value : DEFAULT_PREFERENCE
  } catch {
    return DEFAULT_PREFERENCE
  }
}

function matches(query: string): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(query).matches
    : false
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === 'system') return matches(DARK_QUERY) ? 'dark' : 'light'
  return preference
}

let state: ThemeState = (() => {
  const preference = readStoredPreference()
  return { preference, resolved: resolveTheme(preference) }
})()
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

function writeAttribute(theme: ResolvedTheme) {
  const root = document.documentElement
  root.dataset.theme = theme
  root.style.colorScheme = theme
}

/**
 * Применяет тему к документу. С анимацией — через View Transitions (мягкое перетекание),
 * где API нет — через временный атрибут с переходами цветов. Сокращённое движение — мгновенно.
 */
function applyTheme(theme: ResolvedTheme, animate: boolean) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (root.dataset.theme === theme) return
  if (!animate || matches(REDUCED_MOTION_QUERY)) {
    writeAttribute(theme)
    return
  }
  if (typeof document.startViewTransition === 'function') {
    document.startViewTransition(() => writeAttribute(theme))
    return
  }
  root.setAttribute('data-theme-transition', '')
  writeAttribute(theme)
  window.setTimeout(() => root.removeAttribute('data-theme-transition'), FALLBACK_TRANSITION_MS)
}

export function getThemeState(): ThemeState {
  return state
}

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function setThemePreference(preference: ThemePreference, { animate = true } = {}) {
  const resolved = resolveTheme(preference)
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference)
  } catch {
    // Хранилище недоступно (приватный режим) — тема просто не запомнится.
  }
  applyTheme(resolved, animate)
  if (state.preference === preference && state.resolved === resolved) return
  state = { preference, resolved }
  emit()
}

/**
 * Следит за системной темой (для режима «Как в системе») и за сменой темы в соседних вкладках.
 * Возвращает функцию отписки.
 */
export function startThemeSync(): () => void {
  applyTheme(state.resolved, false)
  const media = window.matchMedia?.(DARK_QUERY)
  const onSystemChange = () => {
    if (state.preference !== 'system') return
    const resolved = resolveTheme('system')
    applyTheme(resolved, true)
    state = { ...state, resolved }
    emit()
  }
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY) return
    const preference = isPreference(event.newValue) ? event.newValue : DEFAULT_PREFERENCE
    const resolved = resolveTheme(preference)
    applyTheme(resolved, true)
    state = { preference, resolved }
    emit()
  }
  media?.addEventListener('change', onSystemChange)
  window.addEventListener('storage', onStorage)
  return () => {
    media?.removeEventListener('change', onSystemChange)
    window.removeEventListener('storage', onStorage)
  }
}

/** Только для тестов: перечитать состояние из хранилища. */
export function resetThemeStoreForTests() {
  const preference = readStoredPreference()
  state = { preference, resolved: resolveTheme(preference) }
  emit()
}
