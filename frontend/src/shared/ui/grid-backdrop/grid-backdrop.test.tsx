import { render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GridBackdrop } from './grid-backdrop'

function mockMatchMedia(matches: (query: string) => boolean) {
  vi.stubGlobal(
    'matchMedia',
    (query: string) =>
      ({
        matches: matches(query),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('GridBackdrop', () => {
  it('без interactive рисует только CSS-сетку и не создаёт холст', () => {
    const { container } = render(<GridBackdrop />)
    expect(container.querySelector('canvas')).toBeNull()
    expect(container.querySelector('.pattern-grid')).not.toBeNull()
  })

  it('interactive не работает с точками', () => {
    const { container } = render(<GridBackdrop pattern="dots" interactive />)
    expect(container.querySelector('canvas')).toBeNull()
  })

  it('interactive без WebGL2 и при «сократить движение» оставляет видимую CSS-сетку', async () => {
    mockMatchMedia((query) => query.includes('reduced-motion'))
    const { container } = render(<GridBackdrop interactive />)
    await waitFor(() => expect(container.querySelector('canvas')).not.toBeNull())
    expect(container.querySelector('.pattern-grid')?.className).not.toContain('invisible')
  })
})
