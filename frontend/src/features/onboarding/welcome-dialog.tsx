import { Button, Dialog, DialogContent } from '@/shared/ui'
import { WELCOME } from './tour/copy'

export interface WelcomeDialogProps {
  open: boolean
  /** «Пройти обучение». */
  onStart: () => void
  /** «Я уже знаком» и `Esc`. */
  onSkip: () => void
  /** Ответ на выбор ещё сохраняется: кнопки не нажать повторно. */
  pending?: boolean
}

/**
 * Приветствие после первого входа: пройти обучение или сразу к работе. Крестика нет, клик по
 * затемнению не закрывает — выбор делается кнопкой; `Esc` равен «Я уже знаком».
 */
export function WelcomeDialog({ open, onStart, onSkip, pending = false }: WelcomeDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && !pending && onSkip()}>
      <DialogContent
        title={WELCOME.title}
        description={WELCOME.text}
        size="sm"
        hideClose
        onInteractOutside={(event) => event.preventDefault()}
        footer={
          <>
            <Button variant="secondary" disabled={pending} onClick={onSkip}>
              {WELCOME.skip}
            </Button>
            <Button variant="primary" loading={pending} onClick={onStart}>
              {WELCOME.start}
            </Button>
          </>
        }
      />
    </Dialog>
  )
}
