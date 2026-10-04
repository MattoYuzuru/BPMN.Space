import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Spotlight } from './spotlight'

const target = { x: 100, y: 80, width: 120, height: 32 }

describe('Spotlight', () => {
  it('вырезает отверстие вокруг элемента с отступом 6 px', () => {
    render(<Spotlight target={target} />)
    const hole = document.querySelector('mask rect[fill="black"]')
    expect(hole).toHaveAttribute('x', '94')
    expect(hole).toHaveAttribute('y', '74')
    expect(hole).toHaveAttribute('width', '132')
    expect(hole).toHaveAttribute('height', '44')
    expect(document.querySelector('svg')).toHaveClass('pointer-events-none')
  })

  it('перехватывает клики четырьмя блоками вокруг выреза, сам вырез свободен', async () => {
    const onBlockedClick = vi.fn()
    const user = userEvent.setup()
    render(<Spotlight target={target} onBlockedClick={onBlockedClick} />)
    const blockers = document.querySelectorAll<HTMLElement>('[data-tour-blocker]')
    expect(blockers).toHaveLength(4)
    const [top, bottom, left, right] = blockers
    expect(top).toHaveStyle({ height: '74px' })
    expect(bottom).toHaveStyle({ top: '118px' })
    expect(left).toHaveStyle({ top: '74px', width: '94px', height: '44px' })
    expect(right).toHaveStyle({ top: '74px', left: '226px', height: '44px' })
    await user.click(top as HTMLElement)
    expect(onBlockedClick).toHaveBeenCalledOnce()
  })

  it('без цели блокирует весь экран и затемняет его без выреза', () => {
    render(<Spotlight target={null} />)
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(1)
    expect(document.querySelector('mask rect[fill="black"]')).toHaveAttribute('width', '0')
  })

  it('block=false не ставит перехватчики, dim=false — только кольцо без затемнения', () => {
    const { rerender } = render(<Spotlight target={target} block={false} />)
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(0)
    rerender(<Spotlight target={target} dim={false} block={false} />)
    expect(document.querySelector('svg')).toHaveClass('invisible')
    // вырез сохраняет координаты, поэтому после возврата затемнения экран не закрыт целиком
    rerender(<Spotlight target={target} />)
    expect(document.querySelector('svg')).not.toHaveClass('invisible')
    expect(document.querySelector('mask rect[fill="black"]')).toHaveAttribute('width', '132')
  })

  it('blockAll держит вырез для вида, но перехватывает клики везде', () => {
    render(<Spotlight target={target} blockAll />)
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(1)
  })

  it('помечен data-tour-layer и сообщает прямоугольник выреза', () => {
    const onFrame = vi.fn()
    render(<Spotlight target={target} onFrame={onFrame} />)
    expect(document.querySelector('[data-tour-layer]')).toHaveAttribute('data-tour-layer')
    expect(onFrame).toHaveBeenLastCalledWith({ x: 94, y: 74, width: 132, height: 44 })
  })

  it('следует за элементом при смене прямоугольника (ресайз, прокрутка)', () => {
    const { rerender } = render(<Spotlight target={target} />)
    rerender(<Spotlight target={{ ...target, y: 20, width: 200 }} />)
    const hole = document.querySelector('mask rect[fill="black"]')
    expect(hole).toHaveAttribute('y', '14')
    expect(hole).toHaveAttribute('width', '212')
  })
})
