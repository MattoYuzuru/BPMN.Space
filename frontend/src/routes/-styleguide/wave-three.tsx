import { useState } from 'react'
import type { MediaProfile, Source } from '@/entities/source'
import { MEDIA_PROFILES } from '@/entities/source'
import { SourceOcrAction } from '@/features/source-ocr'
import { formatClock } from '@/shared/lib/format'
import { Badge, Button, Card, Icon, MediaPlayer, Slider, Tag } from '@/shared/ui'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

// Тихий WAV-заголовок без данных: витрина не грузит медиа с сервера.
const SILENT_WAV =
  'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA='

const segments = [
  { start_sec: 0, end_sec: 30, speaker: 'Иван', text: 'Диспетчер согласует заявку.' },
  { start_sec: 30, end_sec: 90, speaker: 'Инженер', text: 'Инженер готовит акт проверки.' },
]

const scan: Source = {
  id: 'demo-scan',
  project_id: 'demo',
  kind: 'file',
  title: 'Скан регламента',
  file_name: 'reglament-scan.pdf',
  content: '',
  status: 'ready',
  active: true,
  origin: 'user',
  trust: 'primary',
  edited_by_human: false,
  created_at: '2026-11-04T10:00:00Z',
  unreadable_pages: [12, 15],
}

function PlayerDemo() {
  const [position, setPosition] = useState(0)
  const [profile, setProfile] = useState<MediaProfile>('sparse')
  return (
    <div className="flex w-full flex-col gap-3">
      <MediaPlayer
        src={SILENT_WAV}
        kind="audio"
        label="Совещание 12.10"
        durationSec={522}
        onTimeUpdate={setPosition}
      />
      <div className="flex items-center gap-2">
        <span className="type-caption text-fg-subtle" data-numeric>
          {formatClock(position)} из 8:42
        </span>
        <Slider
          label="Пример перемотки"
          value={position}
          max={522}
          formatValue={formatClock}
          showValue
          onValueChange={setPosition}
        />
      </div>
      <ul aria-label="Реплики записи" className="flex flex-col gap-0.5">
        {segments.map((segment) => (
          <li key={segment.start_sec}>
            <Button
              variant="ghost"
              size="sm"
              className="h-auto w-full justify-start gap-2 py-1 whitespace-normal text-left"
              onClick={() => setPosition(segment.start_sec)}
            >
              <span className="font-mono type-caption text-fg-subtle">
                {formatClock(segment.start_sec)}
              </span>
              <span className="type-caption font-medium text-fg-muted">{segment.speaker}</span>
              <span className="type-caption text-fg">{segment.text}</span>
            </Button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-1.5">
        {MEDIA_PROFILES.map((item) => (
          <Button
            key={item.value}
            size="sm"
            variant={profile === item.value ? 'secondary' : 'ghost'}
            leadingIcon={item.icon}
            onClick={() => setProfile(item.value)}
          >
            {item.label}
          </Button>
        ))}
      </div>
      <Caption>
        Профиль меняет число кадров и цену: «Только звук» дешевле, «Подробно» видит все шаги. Выбор
        показывается до загрузки с оценкой.
      </Caption>
    </div>
  )
}

/** Волна 3: плеер, реплики, сканы и профили записи. */
export function WaveThreeSection() {
  return (
    <Section
      id="wave3"
      eyebrow="25 Волна 3"
      title="Плеер, сканы и профили записи"
      lead="Запись играет в листе источника: перемотка по таймкоду цитаты и репликам. Сканы PDF распознаются отдельным действием, а профиль записи выбирается до загрузки с оценкой."
    >
      <SpecimenGrid>
        <Specimen title="Плеер и реплики" note="MediaPlayer, Slider, Slider">
          <PlayerDemo />
        </Specimen>
        <Specimen title="Распознавание сканов" note="SourceOcrAction">
          <div className="flex w-full flex-col gap-3">
            <Card variant="outline" padding="sm" className="flex flex-wrap items-center gap-2">
              <Icon name="file-text" size={16} className="text-fg-subtle" />
              <span className="type-ui text-fg">Скан регламента.pdf</span>
              <Tag icon="file-description">PDF</Tag>
              <Badge tone="amber" variant="outline" icon="alert-triangle">
                2 страницы без текста
              </Badge>
            </Card>
            <SourceOcrAction source={scan} projectId="demo" canEdit nodes={[]} />
            <Caption>
              OCR читает только оставшиеся страницы; готовые не оплачиваются заново, текст можно
              править как любой производный материал.
            </Caption>
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
