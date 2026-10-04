import { render } from '@testing-library/react'
import { useDocumentMeta } from './use-document-meta'

function Page() {
  useDocumentMeta('referrer', 'no-referrer')
  return null
}

const meta = (name: string) =>
  document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content

describe('useDocumentMeta', () => {
  it('ставит тег на время монтирования и убирает при уходе', () => {
    const { unmount } = render(<Page />)
    expect(meta('referrer')).toBe('no-referrer')
    unmount()
    expect(meta('referrer')).toBeUndefined()
  })

  it('возвращает прежний тег с тем же именем', () => {
    const original = document.createElement('meta')
    original.name = 'referrer'
    original.content = 'origin'
    document.head.append(original)
    const { unmount } = render(<Page />)
    expect(document.head.querySelectorAll('meta[name="referrer"]')).toHaveLength(1)
    expect(meta('referrer')).toBe('no-referrer')
    unmount()
    expect(meta('referrer')).toBe('origin')
    original.remove()
  })
})
