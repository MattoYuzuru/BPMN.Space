import { screen } from '@testing-library/react'
import { useState } from 'react'
import { renderUi } from '@/test/render'
import { Field } from '../field/field'
import { SecretInput } from './secret-input'

function Harness() {
  const [value, setValue] = useState('sk-live-secret')
  return (
    <Field label="API-ключ">
      <SecretInput value={value} onChange={(event) => setValue(event.target.value)} />
    </Field>
  )
}

describe('SecretInput', () => {
  it('скрыт по умолчанию, глаз показывает значение', async () => {
    const { user } = renderUi(<Harness />)
    const input = screen.getByLabelText('API-ключ') as HTMLInputElement
    expect(input).toHaveAttribute('type', 'password')
    // Подсказываем браузеру и менеджерам паролей не сохранять секрет.
    expect(input).toHaveAttribute('autocomplete', 'new-password')
    expect(input).toHaveAttribute('data-1p-ignore')
    expect(input).toHaveAttribute('data-lpignore', 'true')
    const toggle = screen.getByRole('button', { name: 'Показать секрет' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    await user.click(toggle)
    expect(input).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Скрыть секрет' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await user.click(screen.getByRole('button', { name: 'Скрыть секрет' }))
    expect(input).toHaveAttribute('type', 'password')
  })

  it('можно показать сразу и переопределить подписи', () => {
    renderUi(
      <SecretInput
        aria-label="Токен"
        defaultValue="x"
        initiallyVisible
        revealLabel="Показать токен"
        hideLabel="Скрыть токен"
      />,
    )
    expect(screen.getByLabelText('Токен')).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Скрыть токен' })).toBeInTheDocument()
  })
})
