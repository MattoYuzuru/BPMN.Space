import { useState } from 'react'
import { Button } from '@/shared/ui'
import { ShareDialog } from './share-dialog'

/** Кнопка «Поделиться» в шапке проекта; показывать только владельцу. */
export function ShareProjectButton({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="sm" leadingIcon="share" onClick={() => setOpen(true)}>
        Поделиться
      </Button>
      <ShareDialog projectId={projectId} open={open} onOpenChange={setOpen} />
    </>
  )
}
