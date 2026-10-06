import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { projectKeys } from '@/entities/project'
import { shareKeys } from '@/entities/share'
import { versionKeys } from '@/entities/version'
import { api, unwrap } from '@/shared/api/client'

export interface Collaborator {
  session_id: string
  user_id: string | null
  display_name: string
  role: 'owner' | 'editor' | 'viewer'
  color_key: number
  cursor: { x: number; y: number } | null
  selection: string[]
  activity: 'idle' | 'editing'
  drag: {
    element_ids: string[]
    start: { x: number; y: number }
    current: { x: number; y: number }
    phase: 'moving' | 'released'
  } | null
}

export interface RealtimeEvent {
  type: string
  [key: string]: unknown
}

export interface CollaborationState {
  connected: boolean
  localSessionId?: string
  participantCount: number
  event: RealtimeEvent | null
}

export interface PresenceStore {
  getSnapshot: () => Collaborator[]
  subscribe: (listener: () => void) => () => void
  set: (participants: Collaborator[]) => void
}

interface PresencePayload {
  cursor: { x: number; y: number } | null
  selection: string[]
  activity: 'idle' | 'editing'
  drag?: Collaborator['drag']
}

// Cursor position is ephemeral: cap it at 20 Hz and always send the latest sample.
const PRESENCE_INTERVAL_MS = 60
const MAX_BUFFERED_SOCKET_BYTES = 64 * 1024

function createPresenceStore(): PresenceStore {
  let snapshot: Collaborator[] = []
  const listeners = new Set<() => void>()
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    set: (participants) => {
      snapshot = participants
      listeners.forEach((listener) => {
        listener()
      })
    },
  }
}

/** Комнатный realtime transport. Данные документа остаются за REST и сохранёнными версиями. */
export function useProjectCollaboration(projectId: string, shareToken?: string, enabled = true) {
  const queryClient = useQueryClient()
  const [presence] = useState(createPresenceStore)
  const socketRef = useRef<WebSocket | null>(null)
  const localSessionIdRef = useRef<string | undefined>(undefined)
  const lastPresenceAt = useRef(0)
  const pendingPresence = useRef<PresencePayload | null>(null)
  const presenceTimer = useRef<number | null>(null)
  const [state, setState] = useState<CollaborationState>({
    connected: false,
    participantCount: 0,
    event: null,
  })

  useEffect(() => {
    if (!enabled || !projectId) return
    presence.set([])
    let closed = false
    let reconnectTimer = 0
    let retry = 0

    const connect = async () => {
      try {
        const response = shareToken
          ? await api.POST('/api/v1/shares/{token}/collaboration-ticket', {
              params: { path: { token: shareToken } },
            })
          : await api.POST('/api/v1/projects/{project_id}/collaboration-ticket', {
              params: { path: { project_id: projectId } },
            })
        const { ticket } = unwrap(response)
        if (closed) return
        const url = new URL(
          `/api/v1/projects/${encodeURIComponent(projectId)}/collaboration/ws`,
          window.location.href,
        )
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
        const socket = new WebSocket(url, ['bpmn.collaboration.v1', `bpmn.ticket.${ticket}`])
        socketRef.current = socket
        socket.onopen = () => {
          retry = 0
          setState((current) => ({ ...current, connected: true }))
          const heartbeat = window.setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
              socket.send(
                JSON.stringify({
                  type: 'ping',
                  protocol_version: 1,
                  sent_at: Date.now(),
                }),
              )
            }
          }, 25_000)
          socket.addEventListener('close', () => window.clearInterval(heartbeat), { once: true })
        }
        socket.onmessage = (message) => {
          let event: RealtimeEvent
          try {
            event = JSON.parse(String(message.data)) as RealtimeEvent
          } catch {
            return
          }
          if (event.type === 'ready') {
            const participants = Array.isArray(event.participants)
              ? (event.participants as Collaborator[])
              : []
            localSessionIdRef.current =
              typeof event.session_id === 'string' ? event.session_id : undefined
            presence.set(participants)
            setState((current) => ({
              ...current,
              localSessionId: typeof event.session_id === 'string' ? event.session_id : undefined,
              event,
              participantCount: participants.length,
            }))
          } else if (event.type === 'presence.snapshot') {
            const participants = Array.isArray(event.participants)
              ? (event.participants as Collaborator[])
              : []
            presence.set(participants)
            setState((current) => ({
              ...current,
              participantCount: participants.length,
            }))
          } else if (event.type === 'presence.changed') {
            const participant = event.participant as Collaborator | undefined
            if (participant && participant.session_id !== localSessionIdRef.current) {
              const current = presence.getSnapshot()
              const isNewParticipant = !current.some(
                (item) => item.session_id === participant.session_id,
              )
              presence.set([
                ...current.filter((item) => item.session_id !== participant.session_id),
                participant,
              ])
              if (isNewParticipant) {
                setState((state) => ({ ...state, participantCount: state.participantCount + 1 }))
              }
            }
          } else if (event.type === 'diagram.version') {
            setState((current) => ({ ...current, event }))
            if (shareToken) {
              void queryClient.invalidateQueries({ queryKey: shareKeys.shared(shareToken) })
            }
          } else if (event.type === 'run.changed') {
            setState((current) => ({ ...current, event }))
            if (event.status === 'queued' || event.status === 'running') {
              void queryClient.invalidateQueries({
                queryKey: shareToken ? shareKeys.shared(shareToken) : projectKeys.detail(projectId),
              })
            }
            if (typeof event.version_id === 'string') {
              void queryClient.invalidateQueries({ queryKey: versionKeys.list(projectId) })
              if (shareToken) {
                void queryClient.invalidateQueries({ queryKey: shareKeys.shared(shareToken) })
              }
            }
          } else if (event.type === 'resync.required') {
            setState((current) => ({ ...current, event }))
            void queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
            void queryClient.invalidateQueries({ queryKey: versionKeys.list(projectId) })
          }
        }
        socket.onclose = () => {
          if (socketRef.current === socket) socketRef.current = null
          presence.set([])
          localSessionIdRef.current = undefined
          setState((current) => ({ ...current, connected: false, participantCount: 0 }))
          if (closed) return
          const delay = Math.min(10_000, 500 * 2 ** Math.min(retry++, 5))
          reconnectTimer = window.setTimeout(() => void connect(), delay)
        }
        socket.onerror = () => socket.close()
      } catch {
        if (closed) return
        setState((current) => ({ ...current, connected: false }))
        const delay = Math.min(10_000, 500 * 2 ** Math.min(retry++, 5))
        reconnectTimer = window.setTimeout(() => void connect(), delay)
      }
    }

    void connect()
    return () => {
      closed = true
      window.clearTimeout(reconnectTimer)
      if (presenceTimer.current !== null) window.clearTimeout(presenceTimer.current)
      presenceTimer.current = null
      pendingPresence.current = null
      socketRef.current?.close(1000, 'Экран закрыт')
      socketRef.current = null
      presence.set([])
      localSessionIdRef.current = undefined
      setState({ connected: false, participantCount: 0, event: null })
    }
  }, [enabled, presence, projectId, queryClient, shareToken])

  const sendPresence = useCallback((update: PresencePayload) => {
    const transmit = (payload: PresencePayload) => {
      const socket = socketRef.current
      if (!socket || socket.readyState !== WebSocket.OPEN) return
      if (socket.bufferedAmount > MAX_BUFFERED_SOCKET_BYTES) return
      socket.send(JSON.stringify({ type: 'presence.update', protocol_version: 1, ...payload }))
      lastPresenceAt.current = performance.now()
    }
    const now = performance.now()
    const remaining = PRESENCE_INTERVAL_MS - (now - lastPresenceAt.current)
    if (remaining <= 0) {
      if (presenceTimer.current !== null) window.clearTimeout(presenceTimer.current)
      presenceTimer.current = null
      pendingPresence.current = null
      transmit(update)
      return
    }

    // Coalesce frequent pointer events into one latest sample, never a stale backlog.
    pendingPresence.current = update
    if (presenceTimer.current === null) {
      presenceTimer.current = window.setTimeout(() => {
        presenceTimer.current = null
        const pending = pendingPresence.current
        pendingPresence.current = null
        if (pending) transmit(pending)
      }, remaining)
    }
  }, [])

  return { ...state, presence, sendPresence }
}
