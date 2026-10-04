import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, m } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRunView } from '@/entities/run'
import { addedElementIds, diagramElements, useSaveDiagram } from '@/entities/version'
import { useDebouncedCallback } from '@/shared/hooks/use-debounced'
import { floatingPanel } from '@/shared/lib/motion'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Skeleton, toast } from '@/shared/ui'
import { type DiagramEditorHandle, LazyDiagramEditor } from '@/widgets/diagram-editor'
import { RunProgress } from '@/widgets/run-progress/run-progress'
import { useWorkspace } from '@/widgets/workspace/model'
import { DiagramEmpty } from './diagram-empty'
import { DiagramToolbar, type MarkerToggles } from './diagram-toolbar'
import { ElementInspector } from './element-inspector'

/** Пауза после последней правки перед сохранением новой версии. */
const SAVE_DEBOUNCE_MS = 1500

/** Центральная панель: схема в bpmn-js, тулбар, ход прогона и карточка элемента. */
export function DiagramPanel() {
  const { project, canEdit, editorRef, viewedVersionId, selectedQuestionId, versions } =
    useWorkspace()
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
  const [ready, setReady] = useState(false)
  const propertiesRef = useRef<HTMLDivElement>(null)
  const [propertiesOpen, setPropertiesOpen] = useState(false)

  const save = useSaveDiagram(project.id)
  const lastSaved = useRef<string | null>(null)
  const debouncedSave = useDebouncedCallback((xml: string) => {
    if (xml === lastSaved.current) return
    lastSaved.current = xml
    save.mutate(xml)
  }, SAVE_DEBOUNCE_MS)

  const xml = version.data?.xml ?? ''
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
      setReady(true)
      const ids = initialFocus.current
      initialFocus.current = undefined
      if (ids?.length) setTimeout(() => handle.focusElement(ids), 300)
    },
    [editorRef],
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
      debouncedSave.run(next)
    },
    [readOnly, debouncedSave],
  )

  if (!latest) {
    return (
      <div className="relative isolate flex h-full flex-col">
        <DiagramEmpty />
        <div className="pointer-events-none absolute inset-x-0 top-4 z-10 flex justify-center">
          <RunProgress projectId={project.id} />
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
        saved={save.isSuccess}
        markers={markers}
        onMarkersChange={setMarkers}
        propertiesOpen={propertiesOpen}
        onPropertiesToggle={() => setPropertiesOpen((open) => !open)}
      />
      <div className="relative flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1" {...tourAnchor(TOUR_ANCHORS.diagramCanvas)}>
          {versionId && version.isPending ? (
            <CanvasSkeleton />
          ) : (
            <LazyDiagramEditor
              ref={editorRef}
              xml={xml}
              readOnly={readOnly}
              highlights={highlights}
              onChange={handleChange}
              onReady={handleReady}
              onElementClick={setInspected}
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

          <div className="pointer-events-none absolute inset-x-0 top-3 z-10 flex justify-center">
            <RunProgress projectId={project.id} />
          </div>

          <div className="pointer-events-none absolute bottom-4 left-4 z-10">
            <AnimatePresence>
              {inspected && version.data && (
                <m.div
                  key={inspected}
                  variants={floatingPanel}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                  className="pointer-events-auto"
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
