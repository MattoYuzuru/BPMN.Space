import { cn } from './cn'

describe('cn', () => {
  it('склеивает классы и убирает конфликты', () => {
    expect(cn('px-2', false, 'px-4')).toBe('px-4')
  })
})
