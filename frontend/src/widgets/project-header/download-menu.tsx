import type { ReactNode } from 'react'
import { useReportOnboardingEvent } from '@/entities/onboarding'
import type { Version } from '@/entities/version'
import { versionLabel } from '@/entities/version'
import { EXPORT_FORMATS, exportDiagram } from '@/features/export-diagram/export'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
  Tooltip,
} from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

/**
 * Скачивание схемы (.bpmn, .svg, .png) и переход к отчёту проверки. Общая для шапки проекта
 * и шапки публичного просмотра: адрес .bpmn берётся из источника версий рабочего места.
 */
export function DownloadMenu({ version, extra }: { version: Version; extra?: ReactNode }) {
  const { project, editorRef, versions } = useWorkspace()
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const report = useReportOnboardingEvent()
  return (
    <DropdownMenu>
      <Tooltip content="Скачать" side="bottom">
        <DropdownMenuTrigger asChild>
          <IconButton
            icon="download"
            size="sm"
            label="Скачать схему"
            tooltip={false}
            {...tourAnchor(TOUR_ANCHORS.headerDownload)}
          />
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="min-w-60">
        <DropdownMenuLabel>{versionLabel(version)}</DropdownMenuLabel>
        {EXPORT_FORMATS.map((item) => (
          <DropdownMenuItem
            key={item.format}
            icon={item.icon}
            onSelect={() =>
              void exportDiagram({
                format: item.format,
                versionId: version.id,
                versionNumber: version.number,
                title: project.title,
                editor: editorRef.current,
                xmlUrl: versions.xmlUrl(version.id),
                onSaved: () => report.mutate('diagram_exported'),
              })
            }
          >
            {item.label}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem icon="shield-check" onSelect={() => setSheet('report')}>
          Отчёт проверки
        </DropdownMenuItem>
        {extra}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
