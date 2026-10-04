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
export type WorkspacePanel = 'sources' | 'questions'
export type QuestionsTab = 'open' | 'assumed' | 'resolved'

/** Просьба показать вкладку панели «Вопросы»; `id` растёт, чтобы повторная просьба тоже срабатывала. */
export interface QuestionsTabRequest {
  tab: QuestionsTab
  id: number
}

/** Просьба развернуть боковую панель; `id` растёт, чтобы повторная просьба тоже срабатывала. */
export interface ExpandRequest {
  panel: WorkspacePanel
  id: number
}

interface WorkspaceUi {
  dialog: WorkspaceDialog
  sheet: WorkspaceSheet
  /** Вопрос, открытый детально (Sheet). */
  questionSheet: string | null
  sourcesCollapsed: boolean
  questionsCollapsed: boolean
  /** Просьба развернуть панель (обучение): раскладка исполняет её сама. */
  expandRequest: ExpandRequest | null
  /** Просьба показать вкладку панели «Вопросы» (обучение показывает «Открытые»). */
  questionsTabRequest: QuestionsTabRequest | null
  /** Подсказка-автодополнение для поля «Текст» диалога текстового источника. */
  textSuggestion: string | null
  setDialog: (dialog: WorkspaceDialog) => void
  setSheet: (sheet: WorkspaceSheet) => void
  openQuestionSheet: (id: string | null) => void
  setCollapsed: (panel: WorkspacePanel, collapsed: boolean) => void
  /** Развернуть панель, если она свёрнута. */
  expandPanel: (panel: WorkspacePanel) => void
  /** Показать вкладку панели «Вопросы». */
  showQuestionsTab: (tab: QuestionsTab) => void
  setTextSuggestion: (text: string | null) => void
  reset: () => void
}

export const useWorkspaceUi = create<WorkspaceUi>((set) => ({
  dialog: null,
  sheet: null,
  questionSheet: null,
  sourcesCollapsed: false,
  questionsCollapsed: false,
  expandRequest: null,
  questionsTabRequest: null,
  textSuggestion: null,
  setDialog: (dialog) => set({ dialog }),
  setSheet: (sheet) => set({ sheet }),
  openQuestionSheet: (questionSheet) => set({ questionSheet }),
  setCollapsed: (panel, collapsed) =>
    set(panel === 'sources' ? { sourcesCollapsed: collapsed } : { questionsCollapsed: collapsed }),
  expandPanel: (panel) =>
    set((state) => ({ expandRequest: { panel, id: (state.expandRequest?.id ?? 0) + 1 } })),
  showQuestionsTab: (tab) =>
    set((state) => ({
      questionsTabRequest: { tab, id: (state.questionsTabRequest?.id ?? 0) + 1 },
    })),
  setTextSuggestion: (textSuggestion) => set({ textSuggestion }),
  reset: () => set({ dialog: null, sheet: null, questionSheet: null, expandRequest: null }),
}))
