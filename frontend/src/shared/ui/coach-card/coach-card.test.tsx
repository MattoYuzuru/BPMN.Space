import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CoachCard, type CoachCardProps } from './coach-card'

function setup(props: Partial<CoachCardProps> = {}) {
  const user = userEvent.setup()
  const handlers = {
    onBack: vi.fn(),
    onNext: vi.fn(),
    onRequestEnd: vi.fn(),
    onConfirmEnd: vi.fn(),
    onCancelEnd: vi.fn(),
    onAction: vi.fn(),
  }
  render(
    <CoachCard
      placement="inline"
      eyebrow="Источники · Шаг 2 из 11"
      title="Добавьте источник"
      text="Откройте меню и выберите пример."
      pageKey="s:0"
      onRequestEnd={handlers.onRequestEnd}
      onConfirmEnd={handlers.onConfirmEnd}
      onCancelEnd={handlers.onCancelEnd}
      actions={[{ id: 'a', label: 'Дальше', variant: 'primary', onClick: handlers.onAction }]}
      {...props}
    />,
  )
  return { user, ...handlers }
}

describe('CoachCard', () => {
  it('подписывает карточку заголовком и показывает счётчик главы и шага', () => {
    setup()
    const card = screen.getByRole('region', { name: 'Добавьте источник' })
    expect(card).toHaveTextContent('Источники · Шаг 2 из 11')
    expect(screen.getByRole('heading', { name: 'Добавьте источник' })).toHaveFocus()
  })

  it('весь текст страницы сразу доступен скринридеру', () => {
    setup()
    expect(
      screen.getByText('Откройте меню и выберите пример.', { selector: '[aria-live]' }),
    ).toBeInTheDocument()
  })

  it('показывает точки страниц и «Назад» только когда передан обработчик', async () => {
    const onBack = vi.fn()
    const { user } = setup({ pageCount: 3, pageIndex: 1, onBack })
    expect(screen.getByText('Страница 2 из 3')).toBeInTheDocument()
    expect(document.querySelectorAll('ol li')).toHaveLength(3)
    await user.click(screen.getByRole('button', { name: 'Назад' }))
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('кнопки по типу шага: действие шага вызывается', async () => {
    const { user, onAction } = setup()
    expect(screen.queryByRole('button', { name: 'Назад' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Дальше' }))
    expect(onAction).toHaveBeenCalledOnce()
  })

  it('крестик и Esc просят завершить обучение', async () => {
    const { user, onRequestEnd } = setup()
    await user.click(screen.getByRole('button', { name: 'Завершить обучение' }))
    expect(onRequestEnd).toHaveBeenCalledTimes(1)
    await user.keyboard('{Escape}')
    expect(onRequestEnd).toHaveBeenCalledTimes(2)
  })

  it('подтверждение внутри самой карточки: «Завершить» и «Продолжить обучение»', async () => {
    const { user, onConfirmEnd, onCancelEnd } = setup({ confirming: true })
    const card = screen.getByRole('region', { name: 'Завершить обучение?' })
    expect(card).toHaveTextContent('Его можно пройти заново в меню аккаунта.')
    expect(screen.getByRole('heading', { name: 'Завершить обучение?' })).toHaveFocus()
    await user.click(within(card).getByRole('button', { name: 'Продолжить обучение' }))
    expect(onCancelEnd).toHaveBeenCalledTimes(1)
    await user.click(within(card).getByRole('button', { name: 'Завершить' }))
    expect(onConfirmEnd).toHaveBeenCalledTimes(1)
    await user.keyboard('{Escape}')
    expect(onCancelEnd).toHaveBeenCalledTimes(2)
  })

  it('→ и Enter на заголовке — «Далее», ← — «Назад»; Enter на кнопке не перехватывается', async () => {
    const onNext = vi.fn()
    const onBack = vi.fn()
    const { user, onAction } = setup({ onNext, onBack })
    await user.keyboard('{ArrowRight}')
    expect(onNext).toHaveBeenCalledTimes(1)
    await user.keyboard('{Enter}')
    expect(onNext).toHaveBeenCalledTimes(2)
    await user.keyboard('{ArrowLeft}')
    expect(onBack).toHaveBeenCalledTimes(1)
    // Enter на сфокусированной кнопке нажимает её, а не «Далее»
    screen.getByRole('button', { name: 'Дальше' }).focus()
    await user.keyboard('{Enter}')
    expect(onAction).toHaveBeenCalledTimes(1)
    expect(onNext).toHaveBeenCalledTimes(2)
  })

  it('состояние «ждём» показывает спиннер, «ошибка» красит заголовок', () => {
    const { container, rerender } = (() => {
      const view = render(
        <CoachCard placement="inline" title="Ждём" text="Документ разбирается." tone="waiting" />,
      )
      return { container: view.container, rerender: view.rerender }
    })()
    expect(container.querySelector('svg.animate-spin')).toBeInTheDocument()
    rerender(<CoachCard placement="inline" title="Сбой" text="Модель не ответила." tone="error" />)
    expect(screen.getByRole('heading', { name: 'Сбой' })).toHaveClass('text-danger-fg')
  })

  it('клик по затемнению (attention) подсвечивает рамку акцентом', () => {
    const { rerender } = render(<CoachCard placement="inline" title="T" text="x" attention={0} />)
    const card = screen.getByRole('region', { name: 'T' })
    expect(card).toHaveClass('border-border')
    rerender(<CoachCard placement="inline" title="T" text="x" attention={1} />)
    expect(card).toHaveClass('border-accent')
  })

  it('по центру экрана — role=dialog без модальности', () => {
    render(<CoachCard placement="center" title="Финал" text="Готово." />)
    const dialog = screen.getByRole('dialog', { name: 'Финал' })
    expect(dialog).toHaveAttribute('aria-modal', 'false')
  })
})
