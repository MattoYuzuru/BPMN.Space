import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { useSession } from '@/entities/session'
import {
  sharedProjectQueryOptions,
  sharePageState,
  useAcceptInvite,
  useProjectAccess,
} from '@/entities/share'
import { AccountMenu } from '@/features/account-menu/account-menu'
import { ThemeSwitch } from '@/features/theme-switch/theme-switch'
import { ApiError } from '@/shared/api/client'
import { useDocumentTitle } from '@/shared/hooks/use-document-title'
import { EntryScene, toast } from '@/shared/ui'
import { ShareStateScreen } from '@/widgets/route-states/route-states'
import { WorkspaceSkeleton } from '@/widgets/skeletons/screen-skeletons'
import { InviteCard, type InviteCardState } from './invite-card'
import { SharedWorkspace, type SharedWorkspaceSearch } from './shared-workspace'

export interface SharePageProps {
  token: string
  search: SharedWorkspaceSearch
  onSearchChange: (patch: Partial<SharedWorkspaceSearch>, options?: { replace?: boolean }) => void
}

/**
 * Публичная страница `/share/<токен>`. Ответ сервера по ссылке превращается в одно из состояний
 * (`sharePageState`): просмотр, приглашение, вход, «недействительна», «срок истёк». Токен живёт
 * только в адресе страницы и в пути запроса к API.
 */
export function SharePage({ token, search, onSearchChange }: SharePageProps) {
  const session = useSession()
  const signedIn = Boolean(session.data?.user)
  const query = useQuery(sharedProjectQueryOptions(token))
  const state = sharePageState({ status: query.status, data: query.data, error: query.error })
  const saveViewerAccess = useAcceptInvite(token)
  const detail =
    state.kind === 'viewer' || state.kind === 'invite' ? state.shared.detail : undefined
  // Проект уже доступен вошедшему (владелец или редактор) — принимать нечего, можно открыть.
  const access = useProjectAccess(detail?.id, signedIn)
  const hasAccess = access.data === 'owner' || access.data === 'editor'
  const { isPending: savingViewer, isSuccess: viewerSaved, mutate: saveViewer } = saveViewerAccess

  // A signed-in person who opens a viewer link gets a persistent read-only membership so the
  // project also appears in their project list. The mutation is explicit HTTP POST, not a GET.
  useEffect(() => {
    if (state.kind !== 'viewer' || !signedIn || savingViewer || viewerSaved) {
      return
    }
    saveViewer(undefined, {
      onSuccess: () => toast.success('Общий проект добавлен в ваш профиль'),
    })
  }, [saveViewer, savingViewer, signedIn, state.kind, viewerSaved])

  useDocumentTitle(
    state.kind === 'invalid' || state.kind === 'expired'
      ? 'Ссылка недействительна'
      : state.kind === 'invite' || state.kind === 'sign-in'
        ? 'Приглашение'
        : undefined,
  )

  if (state.kind === 'loading') return <WorkspaceSkeleton />
  if (state.kind === 'invalid' || state.kind === 'expired') {
    return <ShareStateScreen kind={state.kind} />
  }
  if (state.kind === 'failed') {
    return (
      <ShareStateScreen kind="failed" error={state.error} onRetry={() => void query.refetch()} />
    )
  }
  if (state.kind === 'viewer') {
    return (
      <SharedWorkspace
        token={token}
        shared={state.shared}
        openProject={hasAccess}
        search={search}
        onSearchChange={onSearchChange}
      />
    )
  }

  return (
    <InviteScreen
      token={token}
      invite={
        state.kind === 'sign-in'
          ? { kind: 'sign-in', token }
          : {
              kind: 'invite',
              projectId: state.shared.detail.id,
              title: state.shared.detail.title,
              checking: access.isLoading,
              hasAccess,
            }
      }
      onGone={() => void query.refetch()}
    />
  )
}

type InviteSource =
  | { kind: 'sign-in'; token: string }
  | { kind: 'invite'; projectId: string; title: string; checking: boolean; hasAccess: boolean }

/** Экран приглашения: тот же каркас, что у входа, — сетка, знак, карточка; в углу тема и аккаунт. */
function InviteScreen({
  token,
  invite,
  onGone,
}: {
  token: string
  invite: InviteSource
  onGone: () => void
}) {
  const navigate = useNavigate()
  const accept = useAcceptInvite(token)

  // Ссылку отозвали или она истекла, пока страница была открыта: экран обновится сам.
  useEffect(() => {
    const error = accept.error
    if (error instanceof ApiError && (error.status === 404 || error.status === 410)) onGone()
  }, [accept.error, onGone])

  const card: InviteCardState =
    invite.kind === 'sign-in'
      ? invite
      : invite.checking
        ? { kind: 'checking', title: invite.title }
        : invite.hasAccess
          ? { kind: 'member', title: invite.title, projectId: invite.projectId }
          : {
              kind: 'accept',
              title: invite.title,
              pending: accept.isPending,
              onAccept: () =>
                accept.mutate(undefined, {
                  onSuccess: (result) => {
                    toast.success('Приглашение принято')
                    void navigate({
                      to: '/projects/$projectId',
                      params: { projectId: result.project_id },
                    })
                  },
                }),
            }

  return (
    <EntryScene
      header={
        <>
          <ThemeSwitch compact />
          <AccountMenu afterLogout={() => window.location.reload()} withChecklist={false} />
        </>
      }
    >
      <InviteCard state={card} />
    </EntryScene>
  )
}
