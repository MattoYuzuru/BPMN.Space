import { screen, waitFor } from '@testing-library/react'
import { renderUi } from '@/test/render'
import { CopyField } from './copy-field'

const SECRET = `bps_${'t'.repeat(43)}`

describe('CopyField', () => {
  it('копирует значение из поля и подтверждает галочкой', async () => {
    const { user } = renderUi(
      <CopyField label="Токен" value={SECRET} copyMessage="Токен скопирован" />,
    )
    const input = screen.getByLabelText('Токен') as HTMLInputElement
    expect(input).toHaveValue(SECRET)
    expect(input).toHaveAttribute('readonly')
    await user.click(screen.getByRole('button', { name: 'Копировать: токен' }))
    await waitFor(async () => expect(await navigator.clipboard.readText()).toBe(SECRET))
  })

  it('секрет скрыт и открывается глазом, но копируется целиком', async () => {
    const { user } = renderUi(<CopyField label="Секретный токен" value={SECRET} secret />)
    const input = screen.getByLabelText('Секретный токен') as HTMLInputElement
    expect(input).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: 'Показать секрет' }))
    expect(input).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('button', { name: 'Копировать: секретный токен' }))
    await waitFor(async () => expect(await navigator.clipboard.readText()).toBe(SECRET))
  })

  it('команда подключения — многострочное поле с подсказкой', () => {
    renderUi(
      <CopyField
        label="Команда подключения"
        hint="Команда заработает после обновления."
        value={'claude mcp add --transport http bpmn-space https://example.test/mcp'}
        multiline
      />,
    )
    expect(screen.getByLabelText('Команда подключения')).toHaveValue(
      'claude mcp add --transport http bpmn-space https://example.test/mcp',
    )
    expect(screen.getByText('Команда заработает после обновления.')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Копировать: команда подключения' }),
    ).toBeInTheDocument()
  })
})
