import { type FormEvent, useState } from 'react'
import { VERSION_ORIGIN, type VersionDetail, versionLabel } from '@/entities/version'
import { cn } from '@/shared/lib/cn'
import { formatRelative } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
  Field,
  Icon,
  IconButton,
  Input,
  Tooltip,
} from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

export interface MarkerToggles {
  assumptions: boolean
  added: boolean
}

/** Состояние автосохранения: `conflict` — коллега сохранил схему раньше, ваша правка не записана. */
export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error' | 'conflict'

export interface DiagramToolbarProps {
  version?: VersionDetail
  latestNumber: number
  isLatest: boolean
  simulationActive?: boolean
  ready: boolean
  saveStatus: SaveStatus
  onRetry?: () => void
  /** Показать «Сохранить версию»; `onCheckpoint` вернёт true, если версия закреплена. */
  canCheckpoint?: boolean
  onCheckpoint?: (label: string) => Promise<boolean>
  markers: MarkerToggles
  onMarkersChange: (markers: MarkerToggles) => void
  propertiesOpen: boolean
  onPropertiesToggle: () => void
}

const toggleClass = (active: boolean) => cn(active && 'bg-pressed text-fg')

/** Тулбар схемы: версия и её статус, маркеры, масштаб, мини-карта, симуляция, свойства, проверка. */
export function DiagramToolbar({
  version,
  latestNumber,
  isLatest,
  ready,
  simulationActive,
  saveStatus,
  onRetry,
  canCheckpoint,
  onCheckpoint,
  markers,
  onMarkersChange,
  propertiesOpen,
  onPropertiesToggle,
}: DiagramToolbarProps) {
  const { editorRef, viewVersion, versions } = useWorkspace()
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const [minimap, setMinimap] = useState(false)
  const [localSimulation, setSimulation] = useState(false)
  const simulation = simulationActive ?? localSimulation
  const origin = version ? VERSION_ORIGIN[version.origin] : null
  const issues = version?.report.lint.length ?? 0
  const assumptions = version?.report.assumptions.length ?? 0

  return (
    <div className="@container flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface px-2.5">
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
        {version && origin && !versions.history && (
          <span className="flex items-center gap-1.5 px-2 type-ui text-fg-muted">
            <Icon name={origin.icon} size={16} />
            {versionLabel(version)}
            <span className="hidden font-normal text-fg-subtle @3xl:inline" data-numeric>
              {formatRelative(new Date(version.created_at))}
            </span>
          </span>
        )}
        {version && origin && versions.history && (
          <Tooltip content="История версий" side="bottom">
            <Button
              variant="ghost"
              size="sm"
              leadingIcon={origin.icon}
              onClick={() => setSheet('versions')}
              className="text-fg-muted"
            >
              {version.checkpoint ? (version.label ?? 'Контрольная точка') : origin.label}
              <span className="hidden font-normal text-fg-subtle @3xl:inline" data-numeric>
                {formatRelative(new Date(version.created_at))}
              </span>
            </Button>
          </Tooltip>
        )}
        {!isLatest && (
          <>
            <Badge tone="amber" icon="lock">
              Только просмотр
            </Badge>
            <Button
              size="sm"
              variant="ghost"
              trailingIcon="arrow-right"
              onClick={() => viewVersion(undefined)}
            >
              К версии {latestNumber}
            </Button>
          </>
        )}
        {isLatest && <SaveIndicator status={saveStatus} onRetry={onRetry} />}
        {isLatest && canCheckpoint && onCheckpoint && (
          <CheckpointButton onCheckpoint={onCheckpoint} />
        )}
      </div>

      <div className="flex shrink-0 items-center gap-0.5">
        <DropdownMenu>
          <Tooltip content="Маркеры на схеме" side="bottom">
            <DropdownMenuTrigger asChild>
              <IconButton icon="eye" size="sm" label="Маркеры на схеме" tooltip={false} />
            </DropdownMenuTrigger>
          </Tooltip>
          <DropdownMenuContent align="end" className="min-w-56">
            <DropdownMenuLabel>Подсвечивать</DropdownMenuLabel>
            <DropdownMenuCheckboxItem
              checked={markers.assumptions}
              onCheckedChange={(checked) => onMarkersChange({ ...markers, assumptions: checked })}
            >
              Допущения{assumptions > 0 ? ` (${assumptions})` : ''}
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={markers.added}
              onCheckedChange={(checked) => onMarkersChange({ ...markers, added: checked })}
            >
              Добавленное в версии
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Divider />
        <IconButton
          icon="zoom-out"
          size="sm"
          label="Уменьшить"
          disabled={!ready}
          onClick={() => editorRef.current?.zoomOut()}
        />
        <IconButton
          icon="zoom-in"
          size="sm"
          label="Увеличить"
          disabled={!ready}
          onClick={() => editorRef.current?.zoomIn()}
        />
        <IconButton
          icon="fit-view"
          size="sm"
          label="Вписать в окно"
          disabled={!ready}
          onClick={() => editorRef.current?.fit()}
        />
        <Divider />
        <IconButton
          icon="minimap"
          size="sm"
          label={minimap ? 'Скрыть мини-карту' : 'Мини-карта'}
          aria-pressed={minimap}
          disabled={!ready}
          className={toggleClass(minimap)}
          onClick={() => setMinimap(editorRef.current?.toggleMinimap() ?? false)}
        />
        <IconButton
          icon={simulation ? 'player-stop' : 'player-play'}
          size="sm"
          label={simulation ? 'Остановить таймлайн' : 'Таймлайн процесса'}
          aria-pressed={simulation}
          disabled={!ready}
          className={toggleClass(simulation)}
          onClick={() => {
            const active = editorRef.current?.toggleSimulation() ?? false
            setSimulation(active)
          }}
          {...tourAnchor(TOUR_ANCHORS.diagramSimulation)}
        />
        <IconButton
          icon="adjustments"
          size="sm"
          label={propertiesOpen ? 'Скрыть свойства' : 'Свойства элемента'}
          aria-pressed={propertiesOpen}
          disabled={!ready}
          className={toggleClass(propertiesOpen)}
          onClick={onPropertiesToggle}
        />
        <Divider />
        <Button
          size="sm"
          variant="ghost"
          leadingIcon="shield-check"
          disabled={!version}
          onClick={() => setSheet('report')}
        >
          Проверка
          {issues > 0 && (
            <Badge tone="amber" className="ml-0.5">
              {issues}
            </Badge>
          )}
        </Button>
      </div>
    </div>
  )
}

function Divider() {
  return <span aria-hidden="true" className="mx-1 h-4 w-px bg-border" />
}

const SAVE_TEXT: Record<Exclude<SaveStatus, 'idle'>, string> = {
  saving: 'Сохраняется…',
  saved: 'Сохранено',
  error: 'Не сохранено',
  conflict: 'Не сохранено: схема изменена',
}

/** Индикатор автосохранения. Область озвучивания постоянная: меняется только её текст. */
function SaveIndicator({ status, onRetry }: { status: SaveStatus; onRetry?: () => void }) {
  return (
    <span className="flex items-center gap-1.5 type-caption text-fg-subtle">
      <span role="status" aria-live="polite" className="flex items-center gap-1.5">
        {status === 'saving' && (
          <span className="size-1.5 animate-breathe rounded-full bg-accent" />
        )}
        {status === 'saved' && <Icon name="check" size={14} className="text-success" />}
        {(status === 'error' || status === 'conflict') && (
          <Icon name="alert-circle" size={14} className="text-danger" />
        )}
        {status !== 'idle' && SAVE_TEXT[status]}
      </span>
      {status === 'error' && onRetry && (
        <Button size="sm" variant="ghost" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </span>
  )
}

/** «Сохранить версию»: закрепляет текущую схему как контрольную точку с необязательным именем. */
function CheckpointButton({ onCheckpoint }: { onCheckpoint: (label: string) => Promise<boolean> }) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    try {
      if (await onCheckpoint(label)) {
        setOpen(false)
        setLabel('')
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Tooltip content="Закрепить текущую схему в истории" side="bottom">
        <Button size="sm" variant="ghost" leadingIcon="flag" onClick={() => setOpen(true)}>
          <span className="hidden @3xl:inline">Сохранить версию</span>
          <span className="sr-only @3xl:hidden">Сохранить версию</span>
        </Button>
      </Tooltip>
      <DialogContent
        size="sm"
        title="Сохранить версию"
        description="Версия останется в истории отдельной точкой, дальнейшие правки пойдут в новую."
      >
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="Название" optional>
            <Input
              value={label}
              maxLength={120}
              placeholder="Например, согласовано с заказчиком"
              onChange={(event) => setLabel(event.target.value)}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button type="submit" loading={busy}>
              Сохранить
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
