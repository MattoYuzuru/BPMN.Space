import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useTypewriter } from './use-typewriter'

// Отдельный файл: motion запоминает prefers-reduced-motion при первом обращении.
describe('useTypewriter при prefers-reduced-motion', () => {
  it('показывает текст сразу целиком', () => {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query) =>
        ({
          matches: query.includes('prefers-reduced-motion'),
          media: query,
          addEventListener: () => {},
          removeEventListener: () => {},
          addListener: () => {},
          removeListener: () => {},
        }) as unknown as MediaQueryList,
    )
    const { result } = renderHook(() => useTypewriter({ text: 'Без анимации' }))
    expect(result.current.text).toBe('Без анимации')
    expect(result.current.done).toBe(true)
  })
})
