import { useState } from 'react'
import { formatClock } from '@/shared/lib/format'
import { Badge, IconButton, Slider, Tag, type TreeItem, TreeView } from '@/shared/ui'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

const MATERIALS: TreeItem[] = [
  {
    id: 'recording',
    label: 'Совещание 12.10.mp4',
    icon: 'video',
    meta: <Badge tone="neutral">8:42</Badge>,
    children: [
      {
        id: 'transcript',
        label: 'Расшифровка: Совещание 12.10.mp4',
        icon: 'transcript',
        meta: (
          <>
            <Badge tone="accent" icon="sparkles">
              ИИ
            </Badge>
            <Badge variant="outline">извлечено</Badge>
            <span className="type-caption text-fg-subtle" data-numeric>
              $0,42
            </span>
          </>
        ),
      },
      {
        id: 'frames',
        label: 'Ключевые кадры (37)',
        icon: 'photo',
        meta: (
          <Badge tone="accent" icon="sparkles">
            ИИ
          </Badge>
        ),
        children: [
          {
            id: 'screen-1',
            label: 'Описание экрана заявки',
            icon: 'photo',
            meta: <Badge variant="outline">по кадрам</Badge>,
          },
        ],
      },
    ],
  },
  {
    id: 'regulation',
    label: 'Регламент ТП.docx',
    icon: 'file-description',
    meta: (
      <>
        <Badge tone="amber" variant="outline">
          2 страницы без текста
        </Badge>
        <Badge tone="amber" variant="outline">
          пересказ
        </Badge>
      </>
    ),
  },
  {
    id: 'agent-note',
    label: 'Конспект поставщика',
    icon: 'notes',
    meta: (
      <Badge tone="accent" icon="user">
        Агент
      </Badge>
    ),
  },
]

/** Плеер-заглушка: перемотка на таймкод цитаты (волна 3). */
function PlayerDemo() {
  const [position, setPosition] = useState(27)
  const [playing, setPlaying] = useState(false)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 rounded-lg border border-border bg-surface p-4">
        <IconButton
          icon={playing ? 'player-pause' : 'player-play'}
          label={playing ? 'Пауза' : 'Слушать'}
          onClick={() => setPlaying((current) => !current)}
        />
        <Slider
          label="Позиция записи"
          value={position}
          min={0}
          max={522}
          step={1}
          formatValue={formatClock}
          showValue
          onValueChange={setPosition}
        />
      </div>
      <Caption>
        Перемотка по таймкоду цитаты: «[00:27]» ставит запись на 0:27. Пока это макет — плеер
        появится вместе с воспроизведением записи.
      </Caption>
    </div>
  )
}

export function MaterialsSection() {
  const [selected, setSelected] = useState<string | null>('transcript')
  return (
    <Section
      id="materials"
      eyebrow="22 Материалы"
      title="Дерево материалов"
      lead="Исходные файлы и полученные из них производные узлы. Метка «ИИ» говорит, что материал собрала система, уровень доверия — можно ли на него опираться в схеме, стоимость — во что обошлась обработка. Записи дополняются таймкодами, а цитата открывает запись на нужном моменте."
    >
      <SpecimenGrid>
        <Specimen title="TreeView" note="ARIA tree, стрелки и Home/End">
          <TreeView
            label="Дерево материалов"
            items={MATERIALS}
            selectedId={selected}
            onSelect={setSelected}
          />
        </Specimen>
        <Specimen title="Метки материала" note="Badge, Tag">
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="accent" icon="sparkles">
                ИИ
              </Badge>
              <Badge tone="accent" icon="user">
                Агент
              </Badge>
              <Badge variant="outline">извлечено</Badge>
              <Badge variant="outline">по кадрам</Badge>
              <Badge variant="outline">внешний</Badge>
              <Badge tone="accent" variant="outline">
                от агента
              </Badge>
              <Badge tone="amber" variant="outline">
                пересказ
              </Badge>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Tag icon="transcript">Расшифровка</Tag>
              <Tag icon="photo">Ключевые кадры</Tag>
              <Tag icon="link">Страница из интернета</Tag>
            </div>
            <Caption>
              «Пересказ» — только навигация: цитаты из него в основания схемы не принимаются. «От
              агента» остаётся у материала, который принёс внешний агент.
            </Caption>
          </div>
        </Specimen>
        <Specimen title="Таймкод в цитате" note="font-mono, data-timecode">
          <p className="type-body max-w-xl text-fg-muted">
            <span className="font-mono text-fg-subtle">[01:12]</span> Иван:{' '}
            <mark className="rounded-xs bg-amber-subtle px-0.5 text-fg decoration-amber/70 underline decoration-dashed underline-offset-4">
              отправляем на согласование
            </mark>
            <br />
            <span className="font-mono text-fg-subtle">[01:20]</span> Экран: карточка заявки, кнопка
            «Согласовать».
          </p>
        </Specimen>
        <Specimen title="Плеер записи" note="Slider, IconButton">
          <PlayerDemo />
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
