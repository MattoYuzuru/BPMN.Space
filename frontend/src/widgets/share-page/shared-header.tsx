import { Link } from '@tanstack/react-router'
import type { ShareRole } from '@/entities/share'
import { Badge, Button } from '@/shared/ui'
import { PublicHeader } from '@/widgets/app-header/public-header'
import { DownloadMenu } from '@/widgets/project-header/download-menu'
import { useWorkspace } from '@/widgets/workspace/model'

/**
 * Шапка публичного просмотра: знак, название проекта и маркер роли. У проверки — «Проверка»,
 * у просмотра — «Только просмотр». Справа — скачивание, переход в проект (если у вошедшего уже
 * есть доступ), тема и вход либо аккаунт.
 */
export function SharedHeader({
  loginRedirect,
  openProject,
  role = 'viewer',
}: {
  loginRedirect: string
  /** У вошедшего есть доступ к проекту — предложить открыть его целиком. */
  openProject: boolean
  role?: ShareRole
}) {
  const { project } = useWorkspace()
  const latest = project.latest_version
  return (
    <PublicHeader
      loginRedirect={loginRedirect}
      actions={
        <>
          {latest && <DownloadMenu version={latest} />}
          {openProject && (
            <Button asChild size="sm" variant="primary" trailingIcon="arrow-right">
              <Link to="/projects/$projectId" params={{ projectId: project.id }}>
                Открыть проект
              </Link>
            </Button>
          )}
        </>
      }
    >
      <span aria-hidden="true" className="h-5 w-px shrink-0 bg-border" />
      <span className="min-w-0 max-w-[32rem] truncate px-1.5 type-subheading text-fg">
        {project.title}
      </span>
      {role === 'reviewer' ? (
        <Badge tone="accent" variant="outline" icon="users" className="shrink-0">
          Проверка
        </Badge>
      ) : (
        <Badge tone="neutral" variant="outline" icon="lock" className="shrink-0">
          Только просмотр
        </Badge>
      )}
    </PublicHeader>
  )
}
