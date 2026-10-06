import { type RefObject, useEffect, useRef, useSyncExternalStore } from 'react'
import { Icon } from '@/shared/ui'
import type { DiagramEditorHandle } from '@/widgets/diagram-editor'
import type { PresenceStore } from './use-project-collaboration'

const COLOR_CLASSES = [
  'text-accent-fg',
  'text-success-fg',
  'text-amber-fg',
  'text-danger-fg',
  'text-accent',
  'text-success',
  'text-amber',
  'text-danger',
]

export function CollaboratorOverlay({
  presence,
  localSessionId,
  editorRef,
  boundsRef,
  viewportRevision,
}: {
  presence: PresenceStore
  localSessionId?: string
  editorRef: RefObject<DiagramEditorHandle | null>
  boundsRef: RefObject<HTMLDivElement | null>
  viewportRevision: number
}) {
  const participants = useSyncExternalStore(
    presence.subscribe,
    presence.getSnapshot,
    presence.getSnapshot,
  )
  // The revision is intentionally read: zoom/pan changes coordinates without new presence data.
  void viewportRevision
  const remoteSelections = participants
    .filter(
      (participant) =>
        participant.session_id !== localSessionId && participant.selection.length > 0,
    )
    .map((participant) => ({
      colorKey: participant.color_key,
      elementIds: participant.selection,
    }))
  const remoteMoves = participants
    .filter((participant) => participant.session_id !== localSessionId && participant.drag !== null)
    .map((participant) => ({
      elementIds: participant.drag?.element_ids ?? [],
      delta: {
        x: (participant.drag?.current.x ?? 0) - (participant.drag?.start.x ?? 0),
        y: (participant.drag?.current.y ?? 0) - (participant.drag?.start.y ?? 0),
      },
    }))
  const selectionSignature = JSON.stringify(remoteSelections)
  const lastSelectionSignature = useRef<string | null>(null)
  const movesSignature = JSON.stringify(remoteMoves)
  const lastMovesSignature = useRef<string | null>(null)
  const editor = editorRef.current
  const bounds = boundsRef.current?.getBoundingClientRect()
  useEffect(() => {
    if (lastSelectionSignature.current === selectionSignature) return
    lastSelectionSignature.current = selectionSignature
    editorRef.current?.setRemoteSelections(remoteSelections)
  }, [editorRef, remoteSelections, selectionSignature])
  useEffect(() => {
    if (lastMovesSignature.current === movesSignature) return
    lastMovesSignature.current = movesSignature
    editorRef.current?.setRemoteMoves(remoteMoves)
  }, [editorRef, movesSignature, remoteMoves])
  if (!editor || !bounds) return null

  return (
    <div className="pointer-events-none absolute inset-0 z-20 overflow-hidden" aria-hidden="true">
      {participants.map((participant) => {
        if (!participant.cursor || participant.session_id === localSessionId) return null
        const point = editor.diagramToScreen(participant.cursor)
        const x = point.x - bounds.left
        const y = point.y - bounds.top
        if (x < 0 || y < 0 || x > bounds.width || y > bounds.height) return null
        const color = COLOR_CLASSES[participant.color_key % COLOR_CLASSES.length]
        return (
          <div
            key={participant.session_id}
            className={`absolute left-0 top-0 ${color}`}
            style={{
              transform: `translate3d(${x}px, ${y}px, 0)`,
              transition: 'transform 60ms linear',
            }}
          >
            <Icon name="pointer" size={20} />
            <span
              className={`absolute left-3 top-4 max-w-40 truncate rounded-sm border border-border bg-surface-raised px-1.5 py-0.5 text-2xs font-medium ${color}`}
            >
              {participant.display_name}
            </span>
          </div>
        )
      })}
    </div>
  )
}
