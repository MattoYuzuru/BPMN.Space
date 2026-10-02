import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef } from 'react'
import { isRunning, projectQueryOptions } from '@/entities/project'
import { useStartRun } from '@/entities/run'
import { AddTextDialog, AddVoiceDialog } from '@/features/add-source/add-source-dialogs'
import { useRegisterCommands } from '@/features/command-palette/model'
import { useRunTracker } from '@/features/run-analysis/use-run-tracker'
import {
  type CommandGroup,
  IconButton,
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
  useDefaultLayout,
  usePanelRef,
} from '@/shared/ui'
import type { DiagramEditorHandle } from '@/widgets/diagram-editor'
import { DiagramPanel } from '@/widgets/diagram-panel/diagram-panel'
import { ProjectHeader } from '@/widgets/project-header/project-header'
import { QuestionSheet } from '@/widgets/questions-panel/question-sheet'
import { QuestionsPanel } from '@/widgets/questions-panel/questions-panel'
import { SourceSheet } from '@/widgets/sources-panel/source-sheet'
import { SourcesPanel } from '@/widgets/sources-panel/sources-panel'
import { ReportSheet } from '@/widgets/version-sheets/report-sheet'
import { VersionsSheet } from '@/widgets/version-sheets/versions-sheet'
import { useWorkspaceUi, type WorkspaceApi, WorkspaceContext } from './model'

export interface WorkspaceSearch {
  question?: string
  version?: string
  source?: string
  mark?: string
}

export interface WorkspaceProps {
  projectId: string
  search: WorkspaceSearch
  onSearchChange: (patch: Partial<WorkspaceSearch>, options?: { replace?: boolean }) => void
}

const COLLAPSED = '44px'

/**
 * Рабочее место проекта: шапка и три панели с изменяемой шириной (источники, схема, вопросы).
 * Боковые панели сворачиваются в узкую полосу; раскладка запоминается между сессиями.
 */
export function Workspace({ projectId, search, onSearchChange }: WorkspaceProps) {
  const { data: project } = useQuery(projectQueryOptions(projectId))
  const editorRef = useRef<DiagramEditorHandle | null>(null)
  const sourcesRef = usePanelRef()
  const questionsRef = usePanelRef()
  const ui = useWorkspaceUi()
  const layout = useDefaultLayout({
    id: 'workspace-panels',
    panelIds: ['sources', 'diagram', 'questions'],
  })

  useRunTracker(projectId, project?.active_run)
  useEffect(() => () => useWorkspaceUi.getState().reset(), [])

  const api = useMemo<WorkspaceApi | null>(() => {
    if (!project) return null
    return {
      project,
      editorRef,
      selectedQuestionId: search.question,
      viewedVersionId: search.version,
      selectQuestion: (id, options) => {
        onSearchChange({ question: id }, { replace: true })
        if (id && options?.focus) {
          const question = project.questions.find((item) => item.id === id)
          if (question?.element_ids.length) editorRef.current?.focusElement(question.element_ids)
          if (questionsRef.current?.isCollapsed()) questionsRef.current.expand()
        }
      },
      openSource: (sourceId, mark) => onSearchChange({ source: sourceId, mark }),
      viewVersion: (versionId) => onSearchChange({ version: versionId }),
      focusElements: (ids) => editorRef.current?.focusElement(ids) ?? false,
    }
  }, [project, search.question, search.version, onSearchChange, questionsRef])

  const commands = useWorkspaceCommands(api)
  useRegisterCommands('workspace', commands)

  if (!api || !project) return null

  return (
    <WorkspaceContext.Provider value={api}>
      <div className="flex h-dvh flex-col bg-bg">
        <ProjectHeader />
        <main className="min-h-0 flex-1">
          <ResizablePanelGroup
            orientation="horizontal"
            defaultLayout={layout.defaultLayout}
            onLayoutChanged={layout.onLayoutChanged}
          >
            <ResizablePanel
              id="sources"
              panelRef={sourcesRef}
              defaultSize="22"
              minSize="220px"
              maxSize="40"
              collapsible
              collapsedSize={COLLAPSED}
              onResize={(size) =>
                ui.setCollapsed('sources', size.inPixels <= Number.parseInt(COLLAPSED, 10) + 1)
              }
            >
              {ui.sourcesCollapsed ? (
                <CollapsedRail
                  side="left"
                  icon="file-text"
                  label="Источники"
                  count={project.sources.filter((source) => source.kind !== 'answer').length}
                  onExpand={() => sourcesRef.current?.expand()}
                />
              ) : (
                <SourcesPanel onCollapse={() => sourcesRef.current?.collapse()} />
              )}
            </ResizablePanel>
            <ResizableHandle />
            <ResizablePanel id="diagram" minSize="420px">
              <DiagramPanel />
            </ResizablePanel>
            <ResizableHandle />
            <ResizablePanel
              id="questions"
              panelRef={questionsRef}
              defaultSize="28"
              minSize="300px"
              maxSize="45"
              collapsible
              collapsedSize={COLLAPSED}
              onResize={(size) =>
                ui.setCollapsed('questions', size.inPixels <= Number.parseInt(COLLAPSED, 10) + 1)
              }
            >
              {ui.questionsCollapsed ? (
                <CollapsedRail
                  side="right"
                  icon="message-question"
                  label="Вопросы"
                  count={project.summary.open + project.summary.new}
                  onExpand={() => questionsRef.current?.expand()}
                />
              ) : (
                <QuestionsPanel onCollapse={() => questionsRef.current?.collapse()} />
              )}
            </ResizablePanel>
          </ResizablePanelGroup>
        </main>
      </div>

      <AddTextDialog
        projectId={project.id}
        open={ui.dialog === 'text'}
        onOpenChange={(open) => ui.setDialog(open ? 'text' : null)}
      />
      <AddVoiceDialog
        projectId={project.id}
        open={ui.dialog === 'voice'}
        onOpenChange={(open) => ui.setDialog(open ? 'voice' : null)}
      />
      <SourceSheet
        sourceId={search.source}
        mark={search.mark}
        onClose={() => onSearchChange({ source: undefined, mark: undefined })}
      />
      <QuestionSheet />
      <ReportSheet />
      <VersionsSheet />
    </WorkspaceContext.Provider>
  )
}

function CollapsedRail({
  side,
  icon,
  label,
  count,
  onExpand,
}: {
  side: 'left' | 'right'
  icon: 'file-text' | 'message-question'
  label: string
  count: number
  onExpand: () => void
}) {
  return (
    <div
      className={
        side === 'left'
          ? 'flex h-full flex-col items-center gap-2 bg-bg-subtle py-2'
          : 'flex h-full flex-col items-center gap-2 bg-surface py-2'
      }
    >
      <IconButton
        icon={side === 'left' ? 'sidebar-left-expand' : 'sidebar-right-expand'}
        size="sm"
        label={`Развернуть: ${label}`}
        tooltip={side === 'left' ? 'right' : 'left'}
        onClick={onExpand}
      />
      <IconButton
        icon={icon}
        size="sm"
        label={label}
        tooltip={side === 'left' ? 'right' : 'left'}
        onClick={onExpand}
      />
      {count > 0 && (
        <span className="type-caption text-fg-subtle" data-numeric>
          {count}
        </span>
      )}
    </div>
  )
}

/** Команды рабочего места в палитре: прогоны, источники, отчёт, версии. */
function useWorkspaceCommands(api: WorkspaceApi | null): CommandGroup | null {
  const projectId = api?.project.id ?? ''
  const start = useStartRun(projectId)
  const setDialog = useWorkspaceUi((state) => state.setDialog)
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const project = api?.project
  const running = project ? isRunning(project.status) : false
  const noSources = !project || project.sources.length === 0
  const hasVersion = Boolean(project?.latest_version)
  return useMemo<CommandGroup | null>(() => {
    if (!project) return null
    return {
      heading: project.title,
      items: [
        {
          id: 'run-analyze',
          label: 'Запустить анализ',
          icon: 'sparkles',
          keywords: ['analyze', 'вопросы', 'прогон'],
          disabled: running || noSources,
          onSelect: () => start.mutate('analyze'),
        },
        {
          id: 'run-build',
          label: 'Построить схему',
          icon: 'diagram',
          keywords: ['build', 'схема', 'bpmn', 'прогон'],
          disabled: running || noSources,
          onSelect: () => start.mutate('build'),
        },
        {
          id: 'add-text',
          label: 'Добавить текстовый источник',
          icon: 'notes',
          keywords: ['источник', 'текст'],
          onSelect: () => setDialog('text'),
        },
        {
          id: 'add-voice',
          label: 'Записать голосовую заметку',
          icon: 'microphone',
          keywords: ['голос', 'микрофон', 'voice'],
          onSelect: () => setDialog('voice'),
        },
        {
          id: 'open-report',
          label: 'Отчёт проверки',
          icon: 'shield-check',
          keywords: ['xsd', 'bpmnlint', 'проверка'],
          disabled: !hasVersion,
          onSelect: () => setSheet('report'),
        },
        {
          id: 'open-versions',
          label: 'История версий',
          icon: 'history',
          keywords: ['версии', 'history'],
          disabled: !hasVersion,
          onSelect: () => setSheet('versions'),
        },
      ],
    }
  }, [project, running, noSources, hasVersion, start.mutate, setDialog, setSheet])
}
