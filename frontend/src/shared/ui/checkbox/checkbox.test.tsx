import { screen } from '@testing-library/react'
import { useState } from 'react'
import { renderUi } from '@/test/render'
import { Field } from '../field/field'
import { Checkbox } from './checkbox'

function Controlled() {
  const [checked, setChecked] = useState(false)
  return (
    <Checkbox
      label="Учитывать допущения"
      checked={checked}
      onCheckedChange={(value) => setChecked(value === true)}
    />
  )
}

describe('Checkbox', () => {
  it('переключается кликом по подписи и пробелом', async () => {
    const { user } = renderUi(<Controlled />)
    const box = screen.getByRole('checkbox', { name: 'Учитывать допущения' })
    expect(box).toHaveAttribute('aria-checked', 'false')
    await user.click(screen.getByText('Учитывать допущения'))
    expect(box).toHaveAttribute('aria-checked', 'true')
    box.focus()
    await user.keyboard(' ')
    expect(box).toHaveAttribute('aria-checked', 'false')
  })

  it('показывает частичное состояние как mixed', () => {
    renderUi(<Checkbox aria-label="Все вопросы" checked="indeterminate" />)
    expect(screen.getByRole('checkbox', { name: 'Все вопросы' })).toHaveAttribute(
      'aria-checked',
      'mixed',
    )
  })

  it('связывает описание и не реагирует, когда выключен', async () => {
    const onChange = vi.fn()
    const { user } = renderUi(
      <Checkbox
        label="Голос"
        description="Распознаётся SpeechKit"
        disabled
        onCheckedChange={onChange}
      />,
    )
    const box = screen.getByRole('checkbox', { name: 'Голос' })
    expect(box).toHaveAccessibleDescription('Распознаётся SpeechKit')
    expect(box).toBeDisabled()
    await user.click(box)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('получает ошибку от Field', () => {
    renderUi(
      <Field label="Согласие" error="Нужно согласие">
        <Checkbox />
      </Field>,
    )
    const box = screen.getByRole('checkbox', { name: 'Согласие' })
    expect(box).toHaveAttribute('aria-invalid', 'true')
    expect(box).toHaveAccessibleDescription('Нужно согласие')
  })
})
