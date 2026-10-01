import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Toaster, toast } from './toast'

describe('toast', () => {
  afterEach(() => {
    act(() => {
      toast.dismiss()
    })
  })

  it('показывает заголовок и описание в живой области «Уведомления»', async () => {
    render(<Toaster />)
    act(() => {
      toast.success('Источник добавлен', { description: 'Регламент ТП.docx, 12 страниц' })
    })
    expect(await screen.findByText('Источник добавлен')).toBeInTheDocument()
    expect(screen.getByText('Регламент ТП.docx, 12 страниц')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /Уведомления/ })).toBeInTheDocument()
  })

  it('выполняет действие из уведомления', async () => {
    const onUndo = vi.fn()
    render(<Toaster />)
    act(() => {
      toast('Вопрос проигнорирован', { action: { label: 'Отменить', onClick: onUndo } })
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Отменить' }))
    expect(onUndo).toHaveBeenCalledOnce()
  })

  it('ошибка и предупреждение используют свои иконки', async () => {
    render(<Toaster />)
    act(() => {
      toast.error('Не удалось распознать голос')
      toast.warning('Схема построена с допущениями')
    })
    await screen.findByText('Не удалось распознать голос')
    expect(document.querySelector('[data-icon="alert-circle"]')).not.toBeNull()
    expect(document.querySelector('[data-icon="alert-triangle"]')).not.toBeNull()
  })
})
