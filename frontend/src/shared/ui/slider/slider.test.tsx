import { screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { formatClock } from '@/shared/lib/format'
import { renderUi } from '@/test/render'
import { Slider } from './slider'

function SeekHarness() {
  const [value, setValue] = useState(30)
  return (
    <Slider
      label="Позиция записи"
      value={value}
      min={0}
      max={120}
      step={5}
      formatValue={formatClock}
      showValue
      onValueChange={setValue}
    />
  )
}

describe('Slider', () => {
  it('бегунок подписан и читает значение в заданном формате', () => {
    renderUi(<Slider label="Громкость" value={40} min={0} max={100} />)
    const slider = screen.getByRole('slider', { name: 'Громкость' })
    expect(slider).toHaveAttribute('aria-valuenow', '40')
    expect(slider).toHaveAttribute('aria-valuemin', '0')
    expect(slider).toHaveAttribute('aria-valuemax', '100')
  })

  it('стрелки двигают значение на шаг и показывают время записи', async () => {
    const { user } = renderUi(<SeekHarness />)
    const slider = screen.getByRole('slider', { name: 'Позиция записи' })
    slider.focus()
    await user.keyboard('{ArrowRight}')
    await waitFor(() => expect(slider).toHaveAttribute('aria-valuenow', '35'))
    expect(screen.getByText('0:35')).toBeInTheDocument()
    await user.keyboard('{Home}')
    await waitFor(() => expect(slider).toHaveAttribute('aria-valuenow', '0'))
  })

  it('выключенный бегунок не меняет значение и не встаёт в Tab', async () => {
    const onChange = vi.fn()
    const { user } = renderUi(
      <div>
        <button type="button">До</button>
        <Slider label="Плеер" value={10} disabled onValueChange={onChange} />
        <button type="button">После</button>
      </div>,
    )
    const slider = screen.getByRole('slider', { name: 'Плеер' })
    expect(slider).toHaveAttribute('data-disabled')
    expect(slider).not.toHaveAttribute('tabindex', '0')
    screen.getByRole('button', { name: 'До' }).focus()
    await user.tab()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'После' }))
    ;(slider as HTMLElement).focus()
    await user.keyboard('{ArrowRight}')
    expect(onChange).not.toHaveBeenCalled()
  })
})
