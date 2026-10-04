import { useEffect, useState } from 'react'
import { useCurrentUser } from '@/entities/session'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger, Icon } from '@/shared/ui'

interface PresentUser {
  id: string
  email: string
  role: 'owner' | 'editor' | 'viewer'
}

/** Живой список авторизованных участников: источник — серверный SSE, не локальный таймер. */
export function PresenceIndicator({ projectId }: { projectId: string }) {
  const currentUser = useCurrentUser()
  const [users, setUsers] = useState<PresentUser[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!currentUser) return
    const stream = new EventSource(`/api/v1/projects/${projectId}/presence/events`)
    const onPresence = (event: MessageEvent<string>) => {
      try {
        const snapshot: { users: PresentUser[] } = JSON.parse(event.data)
        setUsers(snapshot.users)
        setConnected(true)
      } catch {
        setConnected(false)
      }
    }
    stream.addEventListener('presence', onPresence as EventListener)
    stream.onerror = () => setConnected(false)
    return () => {
      stream.removeEventListener('presence', onPresence as EventListener)
      stream.close()
    }
  }, [projectId, currentUser])

  if (!currentUser) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="ghost" aria-label="Участники на доске" className="gap-1.5">
          <Icon name="users" size={16} />
          <span data-numeric>{connected ? users.length : 'Подключение'}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64 p-2">
        <p className="px-2 py-1 type-label text-fg-subtle">Сейчас на доске</p>
        {connected ? (
          users.map((user) => (
            <p key={user.id} className="truncate rounded-xs px-2 py-1.5 type-ui text-fg">
              {user.email === currentUser.email ? `${user.email} (вы)` : user.email}
              <span className="ml-1 type-caption text-fg-subtle">
                {user.role === 'viewer' ? 'просмотр' : 'редактирование'}
              </span>
            </p>
          ))
        ) : (
          <p className="px-2 py-1.5 type-caption text-fg-muted">Подключаем список участников</p>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
