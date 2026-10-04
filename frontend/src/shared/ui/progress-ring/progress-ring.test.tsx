import { render, screen } from '@testing-library/react'
import { DoneMark } from '../done-mark/done-mark'
import { ProgressRing } from './progress-ring'

describe('ProgressRing', () => {
  it('с подписью — картинка для скринридера; дуга растёт пропорционально', () => {
    const { container } = render(<ProgressRing value={3} max={12} label="Выполнено 3 из 12" />)
    expect(screen.getByRole('img', { name: 'Выполнено 3 из 12' })).toBeInTheDocument()
    const arc = container.querySelectorAll('circle')[1]
    const circumference = Number(arc?.getAttribute('stroke-dasharray'))
    expect(Number(arc?.getAttribute('stroke-dashoffset'))).toBeCloseTo(circumference * 0.75)
  })

  it('без подписи скрыто от скринридера', () => {
    const { container } = render(<ProgressRing value={0} max={12} />)
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true')
    expect(container.querySelectorAll('circle')).toHaveLength(1)
  })

  it('все выполнены — галочка и зелёная дорожка', () => {
    const { container } = render(<ProgressRing value={12} max={12} />)
    expect(container.querySelector('[data-complete]')).not.toBeNull()
    expect(container.querySelector('[data-icon="check"]')).not.toBeNull()
    expect(container.querySelector('circle')).toHaveClass('stroke-success')
  })
})

describe('DoneMark', () => {
  it('отмечена только когда done; не интерактивна', () => {
    const { container, rerender } = render(<DoneMark done={false} />)
    expect(container.firstElementChild).not.toHaveAttribute('data-done')
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    rerender(<DoneMark done />)
    expect(container.firstElementChild).toHaveAttribute('data-done', 'true')
  })
})
