import { useState } from 'react'
import { useReportOnboardingEvent } from '@/entities/onboarding'
import { VERSION_ORIGIN, type VersionDetail, versionLabel } from '@/entities/version'
import { cn } from '@/shared/lib/cn'
import { formatRelative } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
  Icon,
  IconButton,
  Tooltip,
} from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

export interface MarkerToggles {
  assumptions: boolean
  added: boolean
}

export interface DiagramToolbarProps {
  version?: VersionDetail
  latestNumber: number
  isLatest: boolean
  ready: boolean
  saving: boolean
  saved: boolean
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
  saving,
  saved,
  markers,
  onMarkersChange,
  propertiesOpen,
  onPropertiesToggle,
}: DiagramToolbarProps) {
  const { editorRef, viewVersion, versions } = useWorkspace()
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const [minimap, setMinimap] = useState(false)
  const [simulation, setSimulation] = useState(false)
  const report = useReportOnboardingEvent()
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
              {origin.label}
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
        {isLatest && (saving || saved) && (
          <span
            key={saving ? 'saving' : 'saved'}
            className="flex items-center gap-1.5 type-caption text-fg-subtle animate-fade-in"
            aria-live="polite"
          >
            {saving ? (
              <>
                <span className="size-1.5 animate-breathe rounded-full bg-accent" />
                Сохраняется
              </>
            ) : (
              <>
                <Icon name="check" size={14} className="text-success" />
                Сохранено
              </>
            )}
          </span>
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
            if (active) report.mutate('simulation_run')
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
