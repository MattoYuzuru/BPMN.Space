import { act, renderHook } from '@testing-library/react'
import { getThemeState, setThemePreference, THEME_STORAGE_KEY, useTheme } from './index'
import { resetThemeStoreForTests } from './theme-store'

describe('тема', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    resetThemeStoreForTests()
  })

  it('по умолчанию светлая', () => {
    expect(getThemeState()).toEqual({ preference: 'light', resolved: 'light' })
  })

  it('запоминает выбор и ставит data-theme на html', () => {
    setThemePreference('dark', { animate: false })
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.style.colorScheme).toBe('dark')
  })

  it('«как в системе» берёт тему из prefers-color-scheme', () => {
    const original = window.matchMedia
    window.matchMedia = ((query: string) => ({
      ...original(query),
      matches: query.includes('dark'),
    })) as typeof window.matchMedia
    setThemePreference('system', { animate: false })
    expect(getThemeState()).toEqual({ preference: 'system', resolved: 'dark' })
    window.matchMedia = original
  })

  it('useTheme переключает тему', () => {
    const { result } = renderHook(() => useTheme())
    expect(result.current.resolved).toBe('light')
    act(() => result.current.toggle())
    expect(result.current.resolved).toBe('dark')
    act(() => result.current.setPreference('light'))
    expect(result.current.preference).toBe('light')
  })

  it('игнорирует мусор в хранилище', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'sepia')
    resetThemeStoreForTests()
    expect(getThemeState().preference).toBe('light')
  })
})
