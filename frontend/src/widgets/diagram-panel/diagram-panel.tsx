import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, m } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useReportOnboardingEvent } from '@/entities/onboarding'
import { projectKeys } from '@/entities/project'
import { useRunView } from '@/entities/run'
import { addedElementIds, diagramElements, useSaveDiagram, versionKeys } from '@/entities/version'
import { CollaboratorOverlay } from '@/features/project-collaboration/collaborator-overlay'
import { useProjectCollaboration } from '@/features/project-collaboration/use-project-collaboration'
import { ApiError } from '@/shared/api/client'
import { useDebouncedCallback } from '@/shared/hooks/use-debounced'
import { cn } from '@/shared/lib/cn'
import { floatingPanel } from '@/shared/lib/motion'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Button, Skeleton, toast } from '@/shared/ui'
import { type DiagramEditorHandle, LazyDiagramEditor } from '@/widgets/diagram-editor'
import { RunProgress } from '@/widgets/run-progress/run-progress'
import { useWorkspace } from '@/widgets/workspace/model'
import { DiagramEmpty } from './diagram-empty'
import { DiagramToolbar, type MarkerToggles } from './diagram-toolbar'
import { ElementInspector } from './element-inspector'

/** Пауза после последней правки перед сохранением новой версии. */
const SAVE_DEBOUNCE_MS = 1500

const INSPECTOR_CORNERS = {
  'top-right': { x: 1, y: 0, className: 'top-4 right-4' },
  'top-left': { x: 0, y: 0, className: 'top-4 left-4' },
  // Нижний правый угол занят обязательным знаком bpmn.io.
  'bottom-left': { x: 0, y: 1, className: 'bottom-4 left-4' },
} as const
type InspectorCorner = keyof typeof INSPECTOR_CORNERS

/** Центральная панель: схема в bpmn-js, тулбар, ход прогона и карточка элемента. */
export function DiagramPanel() {
  const {
    project,
    canEdit,
    editorRef,
    viewedVersionId,
    selectedQuestionId,
    versions,
    collaborationShareToken,
  } = useWorkspace()
  const queryClient = useQueryClient()
  const latest = project.latest_version
  const versionId = viewedVersionId ?? latest?.id
  const version = useQuery({ ...versions.detail(versionId ?? ''), enabled: !!versionId })
  const versionList = useQuery({ ...versions.list(project.id), enabled: !!latest })
  const run = useRunView(project.id)
  const isLatest = !viewedVersionId || viewedVersionId === latest?.id
  // Анализ схему не меняет — править можно; сборка заменит схему, поэтому на её время только просмотр.
  const building = project.status === 'building'
  const readOnly = !isLatest || building || !canEdit

  const [markers, setMarkers] = useState<MarkerToggles>({ assumptions: true, added: true })
  const [inspected, setInspected] = useState<string | null>(null)
  const [inspectorCorner, setInspectorCorner] = useState<InspectorCorner>('bottom-left')
  const inspectionPoint = useRef<{ x: number; y: number } | null>(null)
  const [simulationActive, setSimulationActive] = useState(false)
  const reportOnboarding = useReportOnboardingEvent()
  const [ready, setReady] = useState(false)
  const propertiesRef = useRef<HTMLDivElement>(null)
  const [propertiesOpen, setPropertiesOpen] = useState(false)

  const save = useSaveDiagram(project.id)
  const lastSaved = useRef<string | null>(null)
  const headVersionRef = useRef<string | null>(latest?.id ?? null)
  const draftXmlRef = useRef<string | null>(null)
  const draftEpochRef = useRef(0)
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve())
  const canvasBoundsRef = useRef<HTMLDivElement>(null)
  const [viewportRevision, setViewportRevision] = useState(0)
  const [selection, setSelection] = useState<string[]>([])
  const selectionRef = useRef<string[]>(selection)
  selectionRef.current = selection
  const [remoteUpdate, setRemoteUpdate] = useState<{ id?: string; number?: number } | null>(null)
  const remoteUpdateRef = useRef(remoteUpdate)
  remoteUpdateRef.current = remoteUpdate
  const markRemoteUpdate = useCallback((update: { id?: string; number?: number } | null) => {
    remoteUpdateRef.current = update
    setRemoteUpdate(update)
  }, [])
  const collaboration = useProjectCollaboration(project.id, collaborationShareToken, isLatest)

  const enqueueSave = useCallback(
    (xml: string) => {
      draftXmlRef.current = xml
      const epoch = draftEpochRef.current
      saveQueueRef.current = saveQueueRef.current
        .catch(() => undefined)
        .then(async () => {
          if (
            epoch !== draftEpochRef.current ||
            xml === lastSaved.current ||
            remoteUpdateRef.current
          ) {
            return
          }
          try {
            const version = await save.mutateAsync({
              xml,
              baseVersionId: headVersionRef.current,
            })
            headVersionRef.current = version.id
            lastSaved.current = xml
            if (draftXmlRef.current === xml) draftXmlRef.current = null
          } catch (error) {
            if (error instanceof ApiError && error.code === 'stale_version') {
              markRemoteUpdate({
                id: error.headVersionId ?? undefined,
                number: error.headVersionNumber ?? undefined,
              })
            }
          }
        })
    },
    [markRemoteUpdate, save],
  )
  const debouncedSave = useDebouncedCallback((xml: string) => {
    enqueueSave(xml)
  }, SAVE_DEBOUNCE_MS)

  // Инвалидация проекта из другого канала не должна импортировать серверный XML поверх черновика.
  const xml = (isLatest && draftXmlRef.current ? draftXmlRef.current : version.data?.xml) ?? ''
  const loadedVersion = version.data
  useEffect(() => {
    if (loadedVersion && !draftXmlRef.current) {
      headVersionRef.current = loadedVersion.id
      lastSaved.current = loadedVersion.xml
    }
  }, [loadedVersion])

  useEffect(() => {
    const event = collaboration.event
    if (!event) return
    const eventVersionId =
      event.type === 'diagram.version'
        ? event.version_id
        : event.type === 'ready'
          ? event.head_version_id
          : event.type === 'run.changed' && event.status === 'succeeded'
            ? event.version_id
            : undefined
    if (typeof eventVersionId !== 'string' || eventVersionId === headVersionRef.current) return
    // Событие собственного сохранения может обогнать HTTP-ответ. После ответа сравним точный id;
    // одинаковый actor не различает вкладки одного аккаунта и локальные вкладки без авторизации.
    if (save.isPending) return
    if (draftXmlRef.current) {
      const id = eventVersionId
      if (remoteUpdate?.id !== id) {
        markRemoteUpdate({
          id,
          number:
            typeof event.number === 'number'
              ? event.number
              : typeof event.head_version_number === 'number'
                ? event.head_version_number
                : undefined,
        })
      }
      return
    }
    void queryClient.invalidateQueries({ queryKey: projectKeys.detail(project.id) })
    void queryClient.invalidateQueries({ queryKey: versionKeys.list(project.id) })
  }, [
    collaboration.event,
    markRemoteUpdate,
    project.id,
    queryClient,
    remoteUpdate?.id,
    save.isPending,
  ])

  const lastCursor = useRef<{ x: number; y: number } | null>(null)
  const dragStart = useRef<{
    elementIds: string[]
    point: { x: number; y: number }
  } | null>(null)
  useEffect(() => {
    const handlePointerMove = (event: globalThis.PointerEvent) => {
      const bounds = canvasBoundsRef.current
      if (
        event.pointerType === 'touch' ||
        !bounds ||
        !(event.target instanceof Node) ||
        !bounds.contains(event.target)
      ) {
        return
      }
      lastCursor.current = editorRef.current?.screenToDiagram(event.clientX, event.clientY) ?? null
      if (lastCursor.current) {
        const drag = dragStart.current
        if (
          drag &&
          event.buttons !== 0 &&
          Math.hypot(lastCursor.current.x - drag.point.x, lastCursor.current.y - drag.point.y) > 4
        ) {
          setInspected(null)
        }
        collaboration.sendPresence({
          cursor: lastCursor.current,
          selection,
          activity: canEdit && selection.length ? 'editing' : 'idle',
          ...(drag && event.buttons !== 0
            ? {
                drag: {
                  element_ids: drag.elementIds,
                  start: drag.point,
                  current: lastCursor.current,
                  phase: 'moving',
                },
              }
            : { drag: null }),
        })
      }
    }
    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (!canEdit || event.button !== 0 || event.pointerType === 'touch') return
      const bounds = canvasBoundsRef.current
      if (!bounds || !(event.target instanceof Element) || !bounds.contains(event.target)) return
      const element = event.target.closest<SVGElement>('[data-element-id]')
      const id = element?.getAttribute('data-element-id')
      const point = editorRef.current?.screenToDiagram(event.clientX, event.clientY)
      if (!id || !point) return
      const selected = selectionRef.current
      dragStart.current = {
        elementIds: selected.includes(id) ? selected : [id],
        point,
      }
    }
    const handlePointerUp = (event: globalThis.PointerEvent) => {
      if (!dragStart.current) return
      const bounds = canvasBoundsRef.current
      const drag = dragStart.current
      dragStart.current = null
      const cursor = bounds?.contains(event.target as Node)
        ? (editorRef.current?.screenToDiagram(event.clientX, event.clientY) ?? lastCursor.current)
        : lastCursor.current
      collaboration.sendPresence({
        cursor,
        selection: selectionRef.current,
        activity: canEdit && selectionRef.current.length ? 'editing' : 'idle',
        ...(drag && cursor
          ? {
              drag: {
                element_ids: drag.elementIds,
                start: drag.point,
                current: cursor,
                phase: 'released' as const,
              },
            }
          : { drag: null }),
      })
    }
    // bpmn-js stops bubbling pointer events while manipulating shapes. Capture at the document
    // level so cursor presence still follows the pointer over the interactive diagram canvas.
    document.addEventListener('pointerdown', handlePointerDown, true)
    document.addEventListener('pointermove', handlePointerMove, { capture: true, passive: true })
    document.addEventListener('pointerup', handlePointerUp, true)
    document.addEventListener('pointercancel', handlePointerUp, true)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true)
      document.removeEventListener('pointermove', handlePointerMove, true)
      document.removeEventListener('pointerup', handlePointerUp, true)
      document.removeEventListener('pointercancel', handlePointerUp, true)
    }
  }, [canEdit, collaboration.sendPresence, editorRef, selection])
  const handleSelectionChange = useCallback(
    (elementIds: string[]) => {
      setSelection(elementIds)
      collaboration.sendPresence({
        cursor: lastCursor.current,
        selection: elementIds,
        activity: canEdit && elementIds.length ? 'editing' : 'idle',
      })
    },
    [canEdit, collaboration.sendPresence],
  )
  useEffect(() => {
    if (!collaboration.connected) return
    collaboration.sendPresence({
      cursor: lastCursor.current,
      selection,
      activity: canEdit && selection.length ? 'editing' : 'idle',
    })
  }, [canEdit, collaboration.connected, collaboration.sendPresence, selection])
  const downloadDraft = useCallback(() => {
    if (!draftXmlRef.current) return
    const href = URL.createObjectURL(new Blob([draftXmlRef.current], { type: 'application/xml' }))
    const link = document.createElement('a')
    link.href = href
    link.download = `${project.title || 'diagram'}-draft.bpmn`
    link.click()
    URL.revokeObjectURL(href)
  }, [project.title])
  const loadRemoteVersion = useCallback(() => {
    downloadDraft()
    debouncedSave.cancel()
    draftEpochRef.current += 1
    markRemoteUpdate(null)
    draftXmlRef.current = null
    void queryClient.invalidateQueries({ queryKey: projectKeys.detail(project.id) })
    void queryClient.invalidateQueries({ queryKey: versionKeys.list(project.id) })
  }, [debouncedSave.cancel, downloadDraft, markRemoteUpdate, project.id, queryClient])

  const elements = useMemo(() => diagramElements(xml), [xml])

  // Предыдущая версия нужна только для маркера «добавлено».
  const previous = versionList.data?.find((item) => item.number === (version.data?.number ?? 0) - 1)
  const previousXml = useQuery({
    ...versions.detail(previous?.id ?? ''),
    enabled: markers.added && !!previous && (version.data?.diff.added ?? 0) > 0,
  })

  const selectedQuestion = project.questions.find((question) => question.id === selectedQuestionId)
  const highlights = useMemo(() => {
    const statusOf = new Map(project.questions.map((question) => [question.id, question.status]))
    return {
      assumptions: markers.assumptions
        ? (version.data?.report.assumptions ?? [])
            .filter((item) => statusOf.get(item.question_id) !== 'resolved')
            .map((item) => item.element_id)
        : [],
      selected: selectedQuestion?.element_ids ?? [],
      added: markers.added && previousXml.data ? addedElementIds(previousXml.data.xml, xml) : [],
    }
  }, [markers, version.data, project.questions, selectedQuestion, previousXml.data, xml])

  // Открыли ссылку с ?question= — когда схема готова, показываем элементы вопроса.
  const initialFocus = useRef(selectedQuestion?.element_ids)
  const handleReady = useCallback(
    (handle: DiagramEditorHandle) => {
      editorRef.current = handle
      handle.setRemoteSelections(
        collaboration.presence
          .getSnapshot()
          .filter(
            (participant) =>
              participant.session_id !== collaboration.localSessionId &&
              participant.selection.length > 0,
          )
          .map((participant) => ({
            colorKey: participant.color_key,
            elementIds: participant.selection,
          })),
      )
      handle.setRemoteMoves(
        collaboration.presence
          .getSnapshot()
          .filter(
            (participant) =>
              participant.session_id !== collaboration.localSessionId && participant.drag !== null,
          )
          .map((participant) => ({
            elementIds: participant.drag?.element_ids ?? [],
            delta: {
              x: (participant.drag?.current.x ?? 0) - (participant.drag?.start.x ?? 0),
              y: (participant.drag?.current.y ?? 0) - (participant.drag?.start.y ?? 0),
            },
          })),
      )
      setReady(true)
      const ids = initialFocus.current
      initialFocus.current = undefined
      if (ids?.length) setTimeout(() => handle.focusElement(ids), 300)
    },
    [collaboration.localSessionId, collaboration.presence, editorRef],
  )

  useEffect(() => {
    editorRef.current?.setPropertiesPanel(propertiesOpen ? propertiesRef.current : null)
  }, [propertiesOpen, editorRef])

  useEffect(
    () => () => {
      editorRef.current = null
    },
    [editorRef],
  )

  const handleChange = useCallback(
    (next: string) => {
      if (readOnly) return
      // Mark the draft immediately, before the debounce timer: a remote version
      // may arrive during this window and must not replace unsaved canvas edits.
      draftXmlRef.current = next
      debouncedSave.run(next)
    },
    [readOnly, debouncedSave],
  )

  const handleElementClick = useCallback((elementId: string) => {
    const bounds = canvasBoundsRef.current?.getBoundingClientRect()
    const point = inspectionPoint.current
    if (bounds && point && bounds.width > 0 && bounds.height > 0) {
      const x = (point.x - bounds.left) / bounds.width
      const y = (point.y - bounds.top) / bounds.height
      const corners = Object.entries(INSPECTOR_CORNERS) as [
        InspectorCorner,
        (typeof INSPECTOR_CORNERS)[InspectorCorner],
      ][]
      corners.sort(
        ([, left], [, right]) =>
          (right.x - x) ** 2 + (right.y - y) ** 2 - ((left.x - x) ** 2 + (left.y - y) ** 2),
      )
      setInspectorCorner(corners[0]?.[0] ?? 'bottom-left')
    }
    setInspected(elementId)
  }, [])

  if (!latest) {
    return (
      <div className="relative isolate flex h-full flex-col">
        <DiagramEmpty />
        <div className="pointer-events-none absolute inset-x-0 top-4 z-10 flex justify-center">
          <RunProgress projectId={project.id} canCancel={canEdit} />
        </div>
      </div>
    )
  }

  return (
    <section aria-label="Схема" className="flex h-full min-w-0 flex-col bg-bg">
      <DiagramToolbar
        version={version.data}
        latestNumber={latest.number}
        isLatest={isLatest}
        ready={ready}
        saving={save.isPending}
        simulationActive={simulationActive}
        saved={save.isSuccess}
        markers={markers}
        onMarkersChange={setMarkers}
        propertiesOpen={propertiesOpen}
        onPropertiesToggle={() => setPropertiesOpen((open) => !open)}
      />
      <div className="relative flex min-h-0 flex-1">
        <div
          ref={canvasBoundsRef}
          className="relative min-w-0 flex-1"
          {...tourAnchor(TOUR_ANCHORS.diagramCanvas)}
          onPointerDownCapture={(event) => {
            if (!(event.target instanceof Element) || !event.target.closest('.djs-element')) return
            inspectionPoint.current = { x: event.clientX, y: event.clientY }
          }}
          onDoubleClickCapture={(event) => {
            if (event.target instanceof Element && event.target.closest('.djs-element'))
              setInspected(null)
          }}
          onPointerLeave={() =>
            collaboration.sendPresence({ cursor: null, selection, activity: 'idle' })
          }
        >
          {versionId && version.isPending && !draftXmlRef.current ? (
            <CanvasSkeleton />
          ) : (
            <LazyDiagramEditor
              ref={editorRef}
              xml={xml}
              readOnly={readOnly}
              highlights={highlights}
              onSimulationChange={(state) => setSimulationActive(state.active)}
              onSimulationStart={() => reportOnboarding.mutate('simulation_run')}
              onChange={handleChange}
              onSelectionChange={handleSelectionChange}
              onViewportChange={() => setViewportRevision((value) => value + 1)}
              onReady={handleReady}
              onElementClick={handleElementClick}
              onError={(error) =>
                toast.error(
                  error.kind === 'import' ? 'Схема не открылась' : 'Правка не сохранена',
                  { description: error.message },
                )
              }
              fallback={<CanvasSkeleton />}
              className="absolute inset-0"
              ariaLabel={`Схема процесса «${project.title}»`}
            />
          )}

          <CollaboratorOverlay
            presence={collaboration.presence}
            localSessionId={collaboration.localSessionId}
            editorRef={editorRef}
            boundsRef={canvasBoundsRef}
            viewportRevision={viewportRevision}
          />
          <span hidden data-viewport-revision={viewportRevision} />

          {remoteUpdate && (
            <div className="absolute inset-x-3 top-11 z-30 flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber/40 bg-surface px-3 py-2 shadow-md">
              <p className="type-caption text-fg">
                {remoteUpdate.number
                  ? `Коллега сохранил версию ${remoteUpdate.number}. Ваши несохранённые изменения пока остаются в этом окне.`
                  : 'Коллега обновил схему. Ваши несохранённые изменения пока остаются в этом окне.'}
              </p>
              <div className="flex shrink-0 gap-2">
                <Button size="sm" variant="secondary" onClick={downloadDraft}>
                  Скачать черновик
                </Button>
                <Button size="sm" onClick={loadRemoteVersion}>
                  Открыть новую версию
                </Button>
              </div>
            </div>
          )}

          <div className="pointer-events-none absolute inset-x-0 top-3 z-10 flex justify-center">
            <RunProgress projectId={project.id} canCancel={canEdit} />
          </div>

          <div
            data-open={Boolean(inspected)}
            className={cn(
              'group/inspector pointer-events-none absolute z-10',
              INSPECTOR_CORNERS[inspectorCorner].className,
            )}
          >
            <AnimatePresence>
              {inspected && version.data && (
                <m.div
                  key={inspected}
                  variants={floatingPanel}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                  className="pointer-events-none group-data-[open=true]/inspector:pointer-events-auto"
                >
                  <ElementInspector
                    elementId={inspected}
                    element={elements.get(inspected)}
                    version={version.data}
                    onClose={() => setInspected(null)}
                  />
                </m.div>
              )}
            </AnimatePresence>
          </div>
          {run?.status === 'running' && run.mode === 'build' && (
            <div className="pointer-events-none absolute inset-0 bg-bg/40 animate-fade-in" />
          )}
        </div>
        <aside
          ref={propertiesRef}
          aria-label="Свойства элемента"
          hidden={!propertiesOpen}
          className="w-80 shrink-0 border-l border-border bg-surface"
        />
      </div>
      {selectedQuestion && !selectedQuestion.element_ids.some((id) => elements.has(id)) && (
        <span className="sr-only" aria-live="polite">
          Элементов вопроса {selectedQuestion.code} нет на этой версии схемы
        </span>
      )}
    </section>
  )
}

function CanvasSkeleton() {
  return (
    <div className="absolute inset-0 grid place-items-center" aria-busy="true">
      <div className="flex w-2/3 max-w-3xl flex-col gap-3">
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-24 rounded-lg" />
      </div>
    </div>
  )
}
