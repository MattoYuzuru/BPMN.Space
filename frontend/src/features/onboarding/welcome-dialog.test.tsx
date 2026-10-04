import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderUi } from '@/test/render'
import { WelcomeDialog } from './welcome-dialog'

describe('WelcomeDialog', () => {
  it('показывает заголовок, текст и две кнопки без крестика', () => {
    renderUi(<WelcomeDialog open onStart={vi.fn()} onSkip={vi.fn()} />)
    const dialog = screen.getByRole('dialog', { name: 'Добро пожаловать в Архитектор' })
    expect(dialog).toHaveTextContent('За пять минут соберём вашу первую схему')
    expect(screen.getByRole('button', { name: 'Пройти обучение' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Я уже знаком' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Закрыть' })).toBeNull()
  })

  it('«Пройти обучение» и «Я уже знаком» вызывают свои обработчики', async () => {
    const onStart = vi.fn()
    const onSkip = vi.fn()
    const { user } = renderUi(<WelcomeDialog open onStart={onStart} onSkip={onSkip} />)
    await user.click(screen.getByRole('button', { name: 'Пройти обучение' }))
    expect(onStart).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: 'Я уже знаком' }))
    expect(onSkip).toHaveBeenCalledTimes(1)
  })

  it('Esc равен «Я уже знаком», клик по затемнению окно не закрывает', async () => {
    const onSkip = vi.fn()
    const { user } = renderUi(<WelcomeDialog open onStart={vi.fn()} onSkip={onSkip} />)
    const overlay = document.querySelector('.bg-overlay')
    expect(overlay).not.toBeNull()
    await user.click(overlay as Element)
    expect(onSkip).not.toHaveBeenCalled()
    await user.keyboard('{Escape}')
    expect(onSkip).toHaveBeenCalledTimes(1)
  })

  it('пока выбор сохраняется, Esc и кнопка отказа не срабатывают повторно', async () => {
    const onSkip = vi.fn()
    const { user } = renderUi(<WelcomeDialog open pending onStart={vi.fn()} onSkip={onSkip} />)
    await user.keyboard('{Escape}')
    expect(onSkip).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Я уже знаком' })).toBeDisabled()
  })

  it('закрытое окно ничего не рисует', () => {
    renderUi(<WelcomeDialog open={false} onStart={vi.fn()} onSkip={vi.fn()} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
