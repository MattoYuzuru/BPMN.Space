import { screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { renderUi } from '@/test/render'
import { SegmentedControl } from './segmented-control'

type View = 'diagram' | 'xml' | 'report'

function Harness({ iconOnly = false }: { iconOnly?: boolean }) {
  const [value, setValue] = useState<View>('diagram')
  return (
    <SegmentedControl<View>
      aria-label="Вид"
      value={value}
      onValueChange={setValue}
      iconOnly={iconOnly}
      options={[
        { value: 'diagram', label: 'Схема', icon: 'diagram' },
        { value: 'xml', label: 'XML', icon: 'file-code' },
        { value: 'report', label: 'Отчёт', icon: 'list-check' },
      ]}
    />
  )
}

describe('SegmentedControl', () => {
  it('это радиогруппа: стрелки меняют выбор, по кругу', async () => {
    const { user } = renderUi(<Harness />)
    expect(screen.getByRole('radiogroup', { name: 'Вид' })).toBeInTheDocument()
    const diagram = screen.getByRole('radio', { name: 'Схема' })
    expect(diagram).toBeChecked()
    diagram.focus()
    // Radix переводит фокус в следующем тике и выбирает вариант, пока стрелка нажата —
    // поэтому держим клавишу, как это происходит в браузере.
    const press = async (key: string) => {
      await user.keyboard(`{${key}>}`)
      await new Promise((resolve) => setTimeout(resolve, 0))
      await user.keyboard(`{/${key}}`)
    }
    await press('ArrowRight')
    await waitFor(() => expect(screen.getByRole('radio', { name: 'XML' })).toBeChecked())
    await press('ArrowLeft')
    await press('ArrowLeft')
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Отчёт' })).toBeChecked())
  })

  it('в режиме иконок подписывает варианты для скринридера', async () => {
    const { user } = renderUi(<Harness iconOnly />)
    await user.click(screen.getByRole('radio', { name: 'Отчёт' }))
    expect(screen.getByRole('radio', { name: 'Отчёт' })).toBeChecked()
    expect(screen.queryByText('Схема')).not.toBeInTheDocument()
  })
})
