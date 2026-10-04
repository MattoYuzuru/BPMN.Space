import { useQuery } from '@tanstack/react-query'
import { hasDiff, VERSION_ORIGIN, type Version, versionLabel } from '@/entities/version'
import { cn } from '@/shared/lib/cn'
import { formatDate, formatTime } from '@/shared/lib/format'
import { Badge, Button, Icon, Sheet, SheetContent, Skeleton } from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

/** История версий схемы: таймлайн с происхождением, датой и диффом; старые — только просмотр. */
export function VersionsSheet() {
  const { project, viewedVersionId, viewVersion, versions: source } = useWorkspace()
  const sheet = useWorkspaceUi((state) => state.sheet)
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const versions = useQuery({ ...source.list(project.id), enabled: sheet === 'versions' })
  const currentId = viewedVersionId ?? project.latest_version?.id

  return (
    <Sheet open={sheet === 'versions'} onOpenChange={(open) => setSheet(open ? 'versions' : null)}>
      <SheetContent size="sm" title="Версии схемы">
        {versions.isPending ? (
          <div className="flex flex-col gap-3" aria-busy="true">
            {[0, 1, 2].map((key) => (
              <Skeleton key={key} className="h-20 rounded-lg" />
            ))}
          </div>
        ) : (
          <ol aria-label="Версии схемы" className="relative flex flex-col">
            {(versions.data ?? []).map((version, index, list) => (
              <VersionItem
                key={version.id}
                version={version}
                latest={index === 0}
                last={index === list.length - 1}
                current={version.id === currentId}
                onOpen={() => {
                  viewVersion(index === 0 ? undefined : version.id)
                  setSheet(null)
                }}
              />
            ))}
          </ol>
        )}
      </SheetContent>
    </Sheet>
  )
}

function VersionItem({
  version,
  latest,
  last,
  current,
  onOpen,
}: {
  version: Version
  latest: boolean
  last: boolean
  current: boolean
  onOpen: () => void
}) {
  const origin = VERSION_ORIGIN[version.origin]
  const date = new Date(version.created_at)
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {!last && (
        <span aria-hidden="true" className="absolute top-7 bottom-0 left-3.5 w-px bg-border" />
      )}
      <span
        className={cn(
          'relative z-10 grid size-7 shrink-0 place-items-center rounded-full border bg-surface',
          current ? 'border-accent text-accent-fg shadow-glow' : 'border-border text-fg-subtle',
        )}
      >
        <Icon name={origin.icon} size={14} />
      </span>
      <div
        className={cn(
          'flex min-w-0 flex-1 flex-col gap-2 rounded-lg border px-3 py-2.5 transition-colors duration-base',
          current ? 'border-accent/40 bg-accent-subtle/50' : 'border-border',
        )}
      >
        <div className="flex items-center gap-2">
          <span className="type-subheading text-fg">{versionLabel(version)}</span>
          {latest && <Badge tone="accent">Последняя</Badge>}
          <span className="ml-auto type-caption text-fg-subtle" data-numeric>
            {formatDate(date)}, {formatTime(date)}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={origin.tone} variant="outline" icon={origin.icon}>
            {origin.label}
          </Badge>
          {hasDiff(version.diff) ? (
            <>
              {version.diff.added > 0 && <Badge tone="success">+{version.diff.added}</Badge>}
              {version.diff.removed > 0 && <Badge tone="danger">−{version.diff.removed}</Badge>}
              {version.diff.changed > 0 && (
                <Badge tone="amber">изменено {version.diff.changed}</Badge>
              )}
            </>
          ) : (
            version.number > 1 && (
              <span className="type-caption text-fg-subtle">Без изменений в узлах</span>
            )
          )}
          {version.report.assumptions.length > 0 && (
            <Badge tone="amber" variant="outline" icon="assumption">
              {version.report.assumptions.length}
            </Badge>
          )}
        </div>
        {!current && (
          <Button
            size="sm"
            variant="ghost"
            trailingIcon="arrow-right"
            className="self-start"
            onClick={onOpen}
          >
            Открыть
          </Button>
        )}
      </div>
    </li>
  )
}
