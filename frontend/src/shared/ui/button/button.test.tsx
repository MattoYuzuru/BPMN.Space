import { screen } from '@testing-library/react'
import { renderUi } from '@/test/render'
import { Icon } from '../icon'
import { IconButton } from '../icon-button/icon-button'
import { Button } from './button'

describe('Button', () => {
  it('по умолчанию type=button и вызывает onClick', async () => {
    const onClick = vi.fn()
    const { user } = renderUi(<Button onClick={onClick}>Построить схему</Button>)
    const button = screen.getByRole('button', { name: 'Построить схему' })
    expect(button).toHaveAttribute('type', 'button')
    await user.click(button)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('в загрузке занят, неактивен и сохраняет подпись для скринридера', async () => {
    const onClick = vi.fn()
    const { user } = renderUi(
      <Button loading onClick={onClick}>
        Сохранить
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Сохранить' })
    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(button).toBeDisabled()
    await user.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('asChild отдаёт стили ссылке', () => {
    renderUi(
      <Button asChild variant="ghost">
        <a href="/styleguide">Стайлгайд</a>
      </Button>,
    )
    expect(screen.getByRole('link', { name: 'Стайлгайд' }).className).toContain('rounded-md')
  })
})

describe('IconButton', () => {
  it('подписан через aria-label и показывает подсказку при фокусе', async () => {
    const { user } = renderUi(<IconButton icon="trash" label="Удалить источник" />)
    await user.tab()
    const button = screen.getByRole('button', { name: 'Удалить источник' })
    expect(button).toHaveFocus()
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Удалить источник')
  })
})

describe('Icon', () => {
  it('декоративная по умолчанию, с подписью — изображение', () => {
    const { container } = renderUi(
      <>
        <Icon name="check" />
        <Icon name="alert-triangle" label="Внимание" />
      </>,
    )
    expect(container.querySelector('[data-icon="check"]')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('img', { name: 'Внимание' })).toHaveAttribute('stroke-width', '1.5')
  })
})
