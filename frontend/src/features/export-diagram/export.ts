import { errorMessage, versionXmlUrl } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import type { DiagramEditorHandle } from '@/widgets/diagram-editor'

export type ExportFormat = 'bpmn' | 'svg' | 'png'

export const EXPORT_FORMATS: {
  format: ExportFormat
  label: string
  icon: 'file-code' | 'vector' | 'photo'
}[] = [
  { format: 'bpmn', label: 'BPMN 2.0 (.bpmn)', icon: 'file-code' },
  { format: 'svg', label: 'Векторный рисунок (.svg)', icon: 'vector' },
  { format: 'png', label: 'Картинка (.png)', icon: 'photo' },
]

/** Имя файла без запрещённых символов: «Техприсоединение, версия 3.bpmn». */
export function exportFileName(title: string, versionNumber: number, format: ExportFormat): string {
  const safe = title
    .replace(/[\\/:*?"<>|]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 80)
  return `${safe || 'Схема'}, версия ${versionNumber}.${format}`
}

function save(href: string, fileName: string) {
  const link = document.createElement('a')
  link.href = href
  link.download = fileName
  link.rel = 'noopener'
  document.body.append(link)
  link.click()
  link.remove()
}

function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  save(url, fileName)
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/**
 * Скачать схему. .bpmn берём с сервера (сохранённая версия — источник правды),
 * SVG и PNG рисует bpmn-js в цветах текущей темы.
 */
export async function exportDiagram(options: {
  format: ExportFormat
  versionId: string
  versionNumber: number
  title: string
  editor: DiagramEditorHandle | null
}) {
  const fileName = exportFileName(options.title, options.versionNumber, options.format)
  try {
    if (options.format === 'bpmn') {
      save(versionXmlUrl(options.versionId), fileName)
      return
    }
    if (!options.editor) throw new Error('Редактор схемы ещё не загрузился')
    if (options.format === 'svg') {
      const svg = await options.editor.exportSvg()
      saveBlob(new Blob([svg], { type: 'image/svg+xml' }), fileName)
    } else {
      saveBlob(await options.editor.exportPng(2), fileName)
    }
  } catch (error) {
    toast.error('Не удалось скачать схему', {
      description: error instanceof Error && error.message ? error.message : errorMessage(error),
    })
  }
}
