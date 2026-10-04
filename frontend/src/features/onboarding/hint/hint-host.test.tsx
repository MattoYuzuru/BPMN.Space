import { act, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Button, Toaster } from '@/shared/ui'
import { renderUi } from '@/test/render'
import HintHost from './hint-host'
import { hideHint, showHint, useHintStore } from './store'

afterEach(() => {
  act(() => hideHint())
})

describe('HintHost', () => {
  it('показывает кольцо и поповер с текстом, «Понятно» закрывает', async () => {
    const prepare = vi.fn()
    const { user, container } = renderUi(
      <>
        <Button data-tour="target">Цель</Button>
        <HintHost />
      </>,
    )
    act(() => showHint({ anchor: 'target', text: 'Нажмите здесь.', prepare }))
    expect(await screen.findByText('Нажмите здесь.')).toBeInTheDocument()
    expect(prepare).toHaveBeenCalledOnce()
    // кольцо без затемнения экрана
    expect(container.querySelector('[data-tour-blocker]')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Понятно' }))
    expect(useHintStore.getState().current).toBeNull()
    expect(screen.queryByText('Нажмите здесь.')).not.toBeInTheDocument()
  })

  it('закрывается по клику на сам элемент и по Esc', async () => {
    const { user } = renderUi(
      <>
        <Button data-tour="target">Цель</Button>
        <HintHost />
      </>,
    )
    act(() => showHint({ anchor: 'target', text: 'Первая.' }))
    await screen.findByText('Первая.')
    await user.click(screen.getByRole('button', { name: 'Цель' }))
    expect(useHintStore.getState().current).toBeNull()

    act(() => showHint({ anchor: 'target', text: 'Вторая.' }))
    await screen.findByText('Вторая.')
    await user.keyboard('{Escape}')
    expect(useHintStore.getState().current).toBeNull()
  })

  it('одна подсказка в момент времени: новая заменяет прежнюю', async () => {
    renderUi(
      <>
        <Button data-tour="a">A</Button>
        <Button data-tour="b">B</Button>
        <HintHost />
      </>,
    )
    act(() => showHint({ anchor: 'a', text: 'Про A.' }))
    await screen.findByText('Про A.')
    act(() => showHint({ anchor: 'b', text: 'Про B.' }))
    await screen.findByText('Про B.')
    expect(screen.queryByText('Про A.')).not.toBeInTheDocument()
  })

  it('якорь не найден за 5 с — обычное уведомление с тем же текстом', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      renderUi(
        <>
          <Toaster />
          <HintHost />
        </>,
      )
      act(() => showHint({ anchor: 'nowhere', text: 'Сначала постройте схему.' }))
      await act(async () => {
        vi.advanceTimersByTime(5200)
      })
      await waitFor(() => expect(useHintStore.getState().current).toBeNull())
      expect(await screen.findByText('Сначала постройте схему.')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})
