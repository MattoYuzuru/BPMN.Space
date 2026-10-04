import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Typewriter } from './typewriter'

const TEXT = 'Опишите процесс своими словами, а модель задаст вопросы.'

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})
afterEach(() => {
  vi.useRealTimers()
})

describe('Typewriter', () => {
  it('отдаёт скринридеру весь текст сразу, а печать скрывает', () => {
    const { container } = render(<Typewriter text={TEXT} />)
    const live = container.querySelector('[aria-live="polite"]')
    expect(live).toHaveTextContent(TEXT)
    const visual = container.querySelector('[aria-hidden="true"]')
    expect(visual).toBeInTheDocument()
    // Виден только напечатанный префикс; остаток занимает место, но невидим.
    expect(visual?.textContent).toBe(TEXT)
    expect(visual?.querySelector('.invisible')?.textContent?.length).toBeGreaterThan(0)
  })

  it('клик по тексту допечатывает его', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const onDone = vi.fn()
    const { container } = render(<Typewriter text={TEXT} onDone={onDone} />)
    expect(container.querySelector('.invisible')?.textContent).toBe(TEXT)
    await user.click(container.firstElementChild as HTMLElement)
    expect(container.querySelector('.invisible')?.textContent).toBe('')
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('любая клавиша, кроме Tab, допечатывает; Tab — нет', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const { container } = render(<Typewriter text={TEXT} />)
    await user.keyboard('{Tab}')
    expect(container.querySelector('.invisible')?.textContent).not.toBe('')
    await user.keyboard('x')
    expect(container.querySelector('.invisible')?.textContent).toBe('')
  })

  it('instant — текст сразу целиком', () => {
    const { container } = render(<Typewriter text={TEXT} instant />)
    expect(container.querySelector('.invisible')?.textContent).toBe('')
  })

  it('печатает сам со временем', () => {
    const { container } = render(<Typewriter text="Короткий текст." />)
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(container.querySelector('.invisible')?.textContent).toBe('')
    expect(screen.getByText('Короткий текст.', { selector: '[aria-live]' })).toBeInTheDocument()
  })
})
