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

  it('выключенный бегунок недоступен', () => {
    renderUi(<Slider label="Плеер" value={10} disabled />)
    expect(screen.getByRole('slider', { name: 'Плеер' })).toHaveAttribute('data-disabled')
  })
})
