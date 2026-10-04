import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import {
  isReadOnly,
  type Project,
  projectCapabilities,
  projectStatusView,
  useDeleteProject,
} from '@/entities/project'
import { formatRelative } from '@/shared/lib/format'
import {
  Badge,
  Card,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Icon,
  IconButton,
  Tag,
  Tooltip,
} from '@/shared/ui'

const MAX_LANES = 3

/** Карточка проекта в списке: статус, дорожки, вопросы, версии и когда менялся. */
export function ProjectCard({ project }: { project: Project }) {
  const status = projectStatusView(project)
  const lanes = project.lanes.slice(0, MAX_LANES)
  const extraLanes = project.lanes.length - lanes.length
  const { counts } = project
  const updated = new Date(project.updated_at)

  return (
    <div className="group/project relative h-full">
      <Card asChild interactive padding="none" className="flex h-full flex-col">
        <Link
          to="/projects/$projectId"
          params={{ projectId: project.id }}
          aria-label={project.title}
          className="flex h-full flex-col"
        >
          <div className="flex flex-1 flex-col gap-3 p-4 pb-3.5">
            <div className="flex h-6 items-center gap-2 pr-8">
              <Badge tone={status.tone} dot>
                {status.label}
              </Badge>
              {isReadOnly(project.access) && <Tag icon="lock">Пример</Tag>}
              {project.access === 'editor' && <Tag icon="users">Общий</Tag>}
            </div>
            <div className="flex flex-col gap-1">
              <h2 className="line-clamp-2 type-subheading text-md text-fg">{project.title}</h2>
              {project.description && (
                <p className="line-clamp-2 type-caption text-fg-muted">{project.description}</p>
              )}
            </div>
            {lanes.length > 0 ? (
              <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
                {lanes.map((lane) => (
                  <Tag key={lane} icon="user" className="max-w-44">
                    {lane}
                  </Tag>
                ))}
                {extraLanes > 0 && (
                  <Tooltip content={project.lanes.slice(MAX_LANES).join(', ')}>
                    <span className="inline-flex h-6 items-center rounded-sm px-1.5 type-caption text-fg-subtle">
                      +{extraLanes}
                    </span>
                  </Tooltip>
                )}
              </div>
            ) : (
              <div className="mt-auto flex items-center gap-1.5 pt-1 type-caption text-fg-subtle">
                <Icon name="diagram" size={14} />
                {counts.sources > 0 ? 'Схема ещё не построена' : 'Добавьте первый источник'}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3 border-t border-border px-4 py-2.5 type-caption text-fg-muted">
            <Counter
              icon="circle-check"
              iconClass="text-success"
              value={counts.questions_resolved}
              label="Решено вопросов"
            />
            <Counter
              icon="circle-dashed"
              iconClass={counts.questions_open > 0 ? 'text-amber' : 'text-fg-subtle'}
              value={counts.questions_open}
              label="Открыто вопросов"
            />
            <Counter
              icon="version"
              iconClass="text-fg-subtle"
              value={counts.versions}
              label="Версий схемы"
            />
            <time
              dateTime={project.updated_at}
              className="ml-auto truncate text-fg-subtle"
              data-numeric
            >
              {formatRelative(updated)}
            </time>
          </div>
        </Link>
      </Card>
      {projectCapabilities(project.access).canManage && <ProjectMenu project={project} />}
    </div>
  )
}

function Counter({
  icon,
  iconClass,
  value,
  label,
}: {
  icon: 'circle-check' | 'circle-dashed' | 'version'
  iconClass: string
  value: number
  label: string
}) {
  return (
    <Tooltip content={label}>
      <span className="flex items-center gap-1" data-numeric>
        <Icon name={icon} size={14} className={iconClass} />
        <span className="sr-only">{label}: </span>
        {value}
      </span>
    </Tooltip>
  )
}

function ProjectMenu({ project }: { project: Project }) {
  const [confirm, setConfirm] = useState(false)
  const remove = useDeleteProject()
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <IconButton
            icon="dots"
            label="Действия с проектом"
            size="sm"
            tooltip={false}
            className="absolute top-3 right-3 opacity-0 transition-opacity duration-base group-focus-within/project:opacity-100 group-hover/project:opacity-100 data-[state=open]:opacity-100"
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem icon="arrow-up-right" asChild>
            <Link to="/projects/$projectId" params={{ projectId: project.id }}>
              Открыть
            </Link>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem icon="trash" tone="danger" onSelect={() => setConfirm(true)}>
            Удалить
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Удалить проект «${project.title}»?`}
        description="Источники, вопросы и все версии схемы удалятся без возможности восстановить."
        confirmLabel="Удалить"
        tone="danger"
        onConfirm={() => remove.mutate(project.id)}
      />
    </>
  )
}
