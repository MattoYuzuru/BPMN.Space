import { useState } from 'react'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Button } from '@/shared/ui'
import { ShareDialog } from './share-dialog'

/** Кнопка «Поделиться» в шапке проекта; показывать только владельцу. */
export function ShareProjectButton({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        size="sm"
        leadingIcon="share"
        onClick={() => setOpen(true)}
        {...tourAnchor(TOUR_ANCHORS.shareOpen)}
      >
        Поделиться
      </Button>
      <ShareDialog projectId={projectId} open={open} onOpenChange={setOpen} />
    </>
  )
}
