import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderUi } from '@/test/render'
import { Button } from '../button/button'
import { ConfirmDialog } from './confirm-dialog'
import { Dialog, DialogContent, DialogTrigger } from './dialog'

describe('Dialog', () => {
  it('открывается, подписан заголовком и описанием, закрывается по Esc', async () => {
    const { user } = renderUi(
      <Dialog>
        <DialogTrigger asChild>
          <Button>Новый проект</Button>
        </DialogTrigger>
        <DialogContent
          title="Новый проект"
          description="Проект — рабочее пространство одной схемы."
          footer={<Button variant="primary">Создать</Button>}
        >
          <p>Тело</p>
        </DialogContent>
      </Dialog>,
    )
    await user.click(screen.getByRole('button', { name: 'Новый проект' }))
    const dialog = await screen.findByRole('dialog', { name: 'Новый проект' })
    expect(dialog).toHaveAccessibleDescription('Проект — рабочее пространство одной схемы.')
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('закрывается крестиком с русской подписью', async () => {
    const { user } = renderUi(
      <Dialog defaultOpen>
        <DialogContent title="Настройки" />
      </Dialog>,
    )
    await user.click(screen.getByRole('button', { name: 'Закрыть' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})

// Radix подписывается на «клик снаружи» после первого такта.
const settle = () => new Promise<void>((resolve) => window.setTimeout(resolve, 20))

describe('Dialog и слой обучения', () => {
  function Harness({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
    return (
      <>
        <Dialog defaultOpen onOpenChange={onOpenChange}>
          <DialogContent title="Окно">
            <p>Тело</p>
          </DialogContent>
        </Dialog>
        <div data-tour-layer="">
          <Button>Далее</Button>
        </div>
        <Button>Снаружи</Button>
      </>
    )
  }

  it('клик и Esc внутри слоя обучения не закрывают окно', async () => {
    const onOpenChange = vi.fn()
    renderUi(<Harness onOpenChange={onOpenChange} />)
    await settle()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const next = screen.getByRole('button', { name: 'Далее', hidden: true })
    await user.click(next)
    fireEvent.keyDown(next, { key: 'Escape' })
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Окно' })).toBeInTheDocument()
  })

  it('обычный клик снаружи по-прежнему закрывает окно', async () => {
    const onOpenChange = vi.fn()
    renderUi(<Harness onOpenChange={onOpenChange} />)
    await settle()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.click(screen.getByRole('button', { name: 'Снаружи', hidden: true }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })
})

describe('ConfirmDialog', () => {
  it('ждёт onConfirm и закрывается после успеха', async () => {
    let resolve: () => void = () => {}
    const onConfirm = vi.fn(() => new Promise<void>((r) => (resolve = r)))
    const { user } = renderUi(
      <ConfirmDialog
        trigger={<Button tone="danger">Удалить</Button>}
        title="Удалить источник?"
        description="Вопросы по нему вернутся в открытые."
        confirmLabel="Удалить источник"
        tone="danger"
        onConfirm={onConfirm}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Удалить' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Удалить источник?' })
    expect(dialog).toHaveAccessibleDescription('Вопросы по нему вернутся в открытые.')
    const confirm = screen.getByRole('button', { name: 'Удалить источник' })
    await user.click(confirm)
    expect(onConfirm).toHaveBeenCalledOnce()
    expect(confirm).toHaveAttribute('aria-busy', 'true')
    resolve()
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  })

  it('остаётся открытым, если действие упало', async () => {
    const { user } = renderUi(
      <ConfirmDialog
        open
        title="Перестроить схему?"
        confirmLabel="Перестроить"
        onConfirm={() => Promise.reject(new Error('сеть'))}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Перестроить' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Перестроить' })).not.toHaveAttribute('aria-busy'),
    )
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  })
})
