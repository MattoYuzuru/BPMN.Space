import { createContext, type RefObject, useContext } from 'react'
import { create } from 'zustand'
import type { ProjectCapabilities, ProjectDetail } from '@/entities/project'
import type { VersionSource } from '@/entities/version'
import type { DiagramEditorHandle } from '@/widgets/diagram-editor'

/**
 * Общее состояние рабочего места для панелей. Выбор (вопрос, открытый источник, версия)
 * живёт в адресе — ссылкой можно поделиться, «назад» работает; открытые окна — в сторе.
 */
export interface WorkspaceApi extends ProjectCapabilities {
  project: ProjectDetail
  /** Откуда берутся версии схемы и куда ведёт скачивание. */
  versions: VersionSource
  editorRef: RefObject<DiagramEditorHandle | null>
  selectedQuestionId?: string
  /** Просматриваемая версия; undefined — последняя. */
  viewedVersionId?: string
  selectQuestion: (id: string | undefined, options?: { focus?: boolean }) => void
  openSource: (sourceId: string, mark?: string) => void
  viewVersion: (versionId: string | undefined) => void
  /** Показать элементы на схеме (плавно центрировать и подсветить). */
  focusElements: (ids: readonly string[]) => boolean
}

export const WorkspaceContext = createContext<WorkspaceApi | null>(null)

export function useWorkspace(): WorkspaceApi {
  const value = useContext(WorkspaceContext)
  if (!value) throw new Error('useWorkspace вне рабочего места')
  return value
}

export type WorkspaceDialog = 'text' | 'voice' | null
export type WorkspaceSheet = 'report' | 'versions' | null

interface WorkspaceUi {
  dialog: WorkspaceDialog
  sheet: WorkspaceSheet
  /** Вопрос, открытый детально (Sheet). */
  questionSheet: string | null
  sourcesCollapsed: boolean
  questionsCollapsed: boolean
  setDialog: (dialog: WorkspaceDialog) => void
  setSheet: (sheet: WorkspaceSheet) => void
  openQuestionSheet: (id: string | null) => void
  setCollapsed: (panel: 'sources' | 'questions', collapsed: boolean) => void
  reset: () => void
}

export const useWorkspaceUi = create<WorkspaceUi>((set) => ({
  dialog: null,
  sheet: null,
  questionSheet: null,
  sourcesCollapsed: false,
  questionsCollapsed: false,
  setDialog: (dialog) => set({ dialog }),
  setSheet: (sheet) => set({ sheet }),
  openQuestionSheet: (questionSheet) => set({ questionSheet }),
  setCollapsed: (panel, collapsed) =>
    set(panel === 'sources' ? { sourcesCollapsed: collapsed } : { questionsCollapsed: collapsed }),
  reset: () => set({ dialog: null, sheet: null, questionSheet: null }),
}))

/**
 * Управление рабочим местом снаружи его дерева (подсказки онбординга): раскладка и выбор вопроса
 * живут в панелях, а не в сторе. `WorkspaceView` регистрирует их, пока открыт.
 */
export interface WorkspaceControls {
  expandPanel: (panel: 'sources' | 'questions') => void
  selectQuestion: WorkspaceApi['selectQuestion']
}

let controls: WorkspaceControls | null = null

/** Зарегистрировать управление; возвращает функцию снятия (только своё). */
export function registerWorkspaceControls(next: WorkspaceControls): () => void {
  controls = next
  return () => {
    if (controls === next) controls = null
  }
}

/** Управление открытым рабочим местом или `null`, если оно не на экране. */
export function getWorkspaceControls(): WorkspaceControls | null {
  return controls
}
