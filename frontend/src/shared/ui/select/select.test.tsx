import { screen } from '@testing-library/react'
import { renderUi } from '@/test/render'
import { Field } from '../field/field'
import { Select } from './select'

const options = [
  { value: 'qwen', label: 'Qwen 3.6' },
  { value: 'alice', label: 'Alice AI' },
  { value: 'gpt', label: 'GPT-OSS 120B', disabled: true },
]

describe('Select', () => {
  it('подписан через Field и показывает плейсхолдер', () => {
    renderUi(
      <Field label="Модель">
        <Select options={options} placeholder="Выберите модель" />
      </Field>,
    )
    const trigger = screen.getByRole('combobox', { name: 'Модель' })
    expect(trigger).toHaveTextContent('Выберите модель')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('открывается с клавиатуры и выбирает вариант', async () => {
    const onValueChange = vi.fn()
    const { user } = renderUi(
      <Select aria-label="Модель" options={options} onValueChange={onValueChange} />,
    )
    const trigger = screen.getByRole('combobox', { name: 'Модель' })
    trigger.focus()
    await user.keyboard('{Enter}')
    const listbox = await screen.findByRole('listbox')
    expect(listbox).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'GPT-OSS 120B' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    await user.click(screen.getByRole('option', { name: 'Alice AI' }))
    expect(onValueChange).toHaveBeenCalledWith('alice')
    expect(trigger).toHaveTextContent('Alice AI')
  })

  it('помечает ошибку', () => {
    renderUi(<Select aria-label="Модель" options={options} invalid />)
    expect(screen.getByRole('combobox', { name: 'Модель' })).toHaveAttribute('aria-invalid', 'true')
  })
})
