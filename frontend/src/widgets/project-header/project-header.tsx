import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useRef, useState } from 'react'
import { isRunning, projectStatusView, useRenameProject } from '@/entities/project'
import { isTechnical } from '@/entities/question'
import { useRunView } from '@/entities/run'
import { RECENT_VERSIONS, VERSION_ORIGIN, versionLabel } from '@/entities/version'
import { ModelPicker } from '@/features/model-picker/model-picker'
import { RebuildFromSources } from '@/features/run-analysis/rebuild-from-sources'
import { RunStartDialog } from '@/features/run-analysis/run-start-dialog'
import { ShareProjectButton } from '@/features/share-project/share-project-button'
import { formatMoney, formatRelative } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  FlowLine,
  Icon,
  Input,
  Tooltip,
} from '@/shared/ui'
import { AppHeader } from '@/widgets/app-header/app-header'
import { SummaryChips } from '@/widgets/run-progress/summary-chips'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'
import { DownloadMenu } from './download-menu'
import { PresenceIndicator } from './presence-indicator'

/** Шапка рабочего места: крошки, название, статус, итоги вопросов, запуск прогонов, версии. */
export function ProjectHeader() {
  const { project, canEdit } = useWorkspace()
  const run = useRunView(project.id)
  const waiting = run?.status === 'waiting'
  const running = isRunning(project.status) || run?.status === 'running' || waiting
  const status = waiting
    ? { label: 'Ждёт вашего действия', tone: 'amber' as const, icon: 'clock' as const }
    : projectStatusView(project)

  return (
    <AppHeader
      compactBrand
      edge={
        running ? <FlowLine state="active" className="absolute inset-x-0 -bottom-px" /> : undefined
      }
      actions={<HeaderActions running={running} />}
    >
      <Icon name="chevron-right" size={14} className="shrink-0 text-fg-subtle" />
      <Link
        to="/"
        className="shrink-0 rounded-sm type-ui text-fg-muted outline-none transition-colors duration-base hover:text-fg focus-visible:ring-2 focus-visible:ring-focus-ring"
      >
        Проекты
      </Link>
      <Icon name="chevron-right" size={14} className="shrink-0 text-fg-subtle" />
      <ProjectTitle />
      <Badge tone={status.tone} icon={status.icon} dot={!waiting} className="shrink-0">
        {status.label}
      </Badge>
      {!canEdit && (
        <Badge tone="neutral" variant="outline" icon="lock" className="shrink-0">
          Только просмотр
        </Badge>
      )}
      {project.questions.some((question) => !isTechnical(question)) && (
        <SummaryChips
          summary={project.summary}
          size="sm"
          className="ml-2 hidden wide:inline-flex"
        />
      )}
    </AppHeader>
  )
}

/** Название проекта с правкой на месте: клик — поле, Enter — сохранить, Esc — отменить. */
function ProjectTitle() {
  const { project, canEdit } = useWorkspace()
  const rename = useRenameProject(project.id)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(project.title)
  const inputRef = useRef<HTMLInputElement>(null)

  const commit = () => {
    const title = draft.trim()
    setEditing(false)
    if (title && title !== project.title) rename.mutate(title)
    else setDraft(project.title)
  }

  if (!canEdit) {
    return (
      <span className="min-w-0 max-w-[32rem] truncate px-1.5 type-subheading text-fg">
        {project.title}
      </span>
    )
  }
  if (editing) {
    return (
      <Input
        ref={inputRef}
        autoFocus
        size="sm"
        value={draft}
        aria-label="Название проекта"
        wrapperClassName="w-80 max-w-full"
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') commit()
          if (event.key === 'Escape') {
            setDraft(project.title)
            setEditing(false)
          }
        }}
      />
    )
  }
  return (
    <Tooltip content="Переименовать" side="bottom">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          setDraft(project.title)
          setEditing(true)
        }}
        className="min-w-0 max-w-[32rem] shrink px-1.5 text-sm text-fg [&>span]:min-w-0"
      >
        <span className="truncate font-semibold">{project.title}</span>
      </Button>
    </Tooltip>
  )
}

function HeaderActions({ running }: { running: boolean }) {
  const { project, canEdit, canShare, viewedVersionId, viewVersion, versions } = useWorkspace()
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const runDialog = useWorkspaceUi((state) => state.runDialog)
  const openRunDialog = useWorkspaceUi((state) => state.openRunDialog)
  const closeRunDialog = useWorkspaceUi((state) => state.closeRunDialog)
  const latest = project.latest_version
  const versionList = useQuery({ ...versions.list(project.id), enabled: !!latest })
  const noSources = project.sources.length === 0
  const viewedId = viewedVersionId ?? latest?.id
  const listed = versionList.data?.find((item) => item.id === viewedId)
  // Просматриваемая старая версия может не попасть в короткий список.
  const loaded = useQuery({
    ...versions.detail(viewedId ?? ''),
    enabled: !!viewedId && !listed && viewedId !== latest?.id,
  })
  const viewed = listed ?? loaded.data ?? latest

  return (
    <>
      {canEdit && (
        <>
          <RunCostLabel projectId={project.id} running={running} />
          <ModelPicker />
          <Tooltip
            content={noSources ? 'Сначала добавьте источник' : 'Найти неясности и задать вопросы'}
            side="bottom"
          >
            <span className="inline-flex">
              <Button
                leadingIcon="sparkles"
                size="sm"
                disabled={noSources || running}
                onClick={() => openRunDialog('analyze')}
              >
                Анализ
              </Button>
            </span>
          </Tooltip>
          <Button
            variant={latest ? 'primary' : 'secondary'}
            leadingIcon="diagram"
            size="sm"
            disabled={noSources || running}
            onClick={() => openRunDialog('build')}
            {...tourAnchor(TOUR_ANCHORS.runBuild)}
          >
            Построить схему
          </Button>
          {latest && (
            <RebuildFromSources
              projectId={project.id}
              baseVersionId={latest.id}
              disabled={noSources || running}
            />
          )}
        </>
      )}

      {latest && viewed && (
        <>
          <span aria-hidden="true" className="mx-1 h-5 w-px bg-border" />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="ghost" trailingIcon="chevron-down" className="gap-1.5">
                <Icon name="version" size={14} className="text-fg-subtle" />
                {versionLabel(viewed)}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              <DropdownMenuLabel>Версии схемы</DropdownMenuLabel>
              {(versionList.data ?? [latest]).slice(0, RECENT_VERSIONS).map((version, index) => (
                <DropdownMenuItem
                  key={version.id}
                  icon={VERSION_ORIGIN[version.origin].icon}
                  onSelect={() => viewVersion(index === 0 ? undefined : version.id)}
                  className={version.id === viewedId ? 'bg-pressed' : undefined}
                >
                  <span className="flex w-full items-center gap-2">
                    {versionLabel(version)}
                    <span className="type-caption text-fg-subtle">
                      {VERSION_ORIGIN[version.origin].label.toLowerCase()}
                    </span>
                    <span className="ml-auto type-caption text-fg-subtle" data-numeric>
                      {formatRelative(new Date(version.created_at))}
                    </span>
                  </span>
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem icon="history" onSelect={() => setSheet('versions')}>
                Вся история
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <DownloadMenu version={viewed} />
        </>
      )}
      {canShare && <ShareProjectButton projectId={project.id} />}
      <PresenceIndicator projectId={project.id} />
      <span aria-hidden="true" className="mx-1 h-5 w-px bg-border" />
      {canEdit && runDialog && (
        <RunStartDialog
          projectId={project.id}
          mode={runDialog}
          open
          onOpenChange={(next) => !next && closeRunDialog()}
        />
      )}
    </>
  )
}

/** Стоимость прогона в шапке: «$2,71 из $10»; обновляется потоком usage. */
function RunCostLabel({ projectId, running }: { projectId: string; running: boolean }) {
  const run = useRunView(projectId)
  const cost = run?.cost?.cost_usd ?? null
  const budget = run?.budget?.cost_usd ?? null
  if (!run || (!running && cost === null)) return null
  const text =
    cost !== null && budget !== null
      ? `${formatMoney(cost)} из ${formatMoney(budget)}`
      : cost !== null
        ? `Потрачено ${formatMoney(cost)}`
        : budget !== null
          ? `Бюджет ${formatMoney(budget)}`
          : null
  if (!text) return null
  return (
    <Tooltip content="Стоимость прогона" side="bottom">
      <span
        className="hidden items-center gap-1.5 rounded-sm px-1.5 type-caption text-fg-muted wide:inline-flex"
        data-numeric
      >
        <Icon name="bolt" size={14} className="text-fg-subtle" />
        {text}
      </span>
    </Tooltip>
  )
}
