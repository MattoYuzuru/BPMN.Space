import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useRef, useState } from 'react'
import { isRunning, projectStatusView, useRenameProject } from '@/entities/project'
import { useRunView, useStartRun } from '@/entities/run'
import { VERSION_ORIGIN, versionLabel } from '@/entities/version'
import { ShareProjectButton } from '@/features/share-project/share-project-button'
import { formatRelative } from '@/shared/lib/format'
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

/** Шапка рабочего места: крошки, название, статус, итоги вопросов, запуск прогонов, версии. */
export function ProjectHeader() {
  const { project, canEdit } = useWorkspace()
  const run = useRunView(project.id)
  const running = isRunning(project.status) || run?.status === 'running'
  const status = projectStatusView(project)

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
      <Badge tone={status.tone} dot className="shrink-0">
        {status.label}
      </Badge>
      {!canEdit && (
        <Badge tone="neutral" variant="outline" icon="lock" className="shrink-0">
          Только просмотр
        </Badge>
      )}
      {project.questions.length > 0 && (
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
  const start = useStartRun(project.id)
  const latest = project.latest_version
  const versionList = useQuery({ ...versions.list(project.id), enabled: !!latest })
  const noSources = project.sources.length === 0
  const viewedId = viewedVersionId ?? latest?.id
  const viewed = versionList.data?.find((item) => item.id === viewedId) ?? latest

  return (
    <>
      {canEdit && (
        <>
          <Tooltip
            content={noSources ? 'Сначала добавьте источник' : 'Найти неясности и задать вопросы'}
            side="bottom"
          >
            <span className="inline-flex">
              <Button
                leadingIcon="sparkles"
                size="sm"
                disabled={noSources || running}
                loading={start.isPending && start.variables === 'analyze'}
                onClick={() => start.mutate('analyze')}
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
            {...tourAnchor(TOUR_ANCHORS.runBuild)}
            loading={start.isPending && start.variables === 'build'}
            onClick={() => start.mutate('build')}
          >
            Построить схему
          </Button>
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
              {(versionList.data ?? [latest]).slice(0, 6).map((version, index) => (
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
      <span aria-hidden="true" className="mx-1 h-5 w-px bg-border" />
    </>
  )
}
