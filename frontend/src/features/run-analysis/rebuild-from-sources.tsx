import { useState } from 'react'
import { useStartRun } from '@/entities/run'
import {
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
} from '@/shared/ui'

/** Обычная сборка бережёт ручные изменения; отдельное действие создаёт версию из источников. */
export function RebuildFromSources({
  projectId,
  baseVersionId,
  disabled,
}: {
  projectId: string
  baseVersionId: string
  disabled: boolean
}) {
  const start = useStartRun(projectId)
  const [confirmedBase, setConfirmedBase] = useState<string | null>(null)

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <IconButton
            icon="chevron-down"
            size="sm"
            label="Другие способы построения"
            disabled={disabled || start.isPending}
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem icon="refresh" onSelect={() => setConfirmedBase(baseVersionId)}>
            Перестроить из источников
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ConfirmDialog
        open={confirmedBase !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmedBase(null)
        }}
        title="Перестроить схему из источников?"
        description="Будет создана новая версия по документам, текстам и ответам. Ручные изменения не переносятся в эту сборку. Текущая схема останется в истории версий."
        confirmLabel="Перестроить"
        onConfirm={async () => {
          if (!confirmedBase) return
          await start.mutateAsync({
            mode: 'build',
            replace_manual: true,
            base_version_id: confirmedBase,
          })
        }}
      />
    </>
  )
}
