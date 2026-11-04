import { useState } from 'react'
import type { Question } from '@/entities/question'
import type { CapabilityCard, Credential } from '@/entities/tool-credential'
import { TechnicalQuestionCard } from '@/features/question-technical/technical-question-card'
import { CapabilityCardView } from '@/features/tools-credentials/capability-card'
import { CredentialRow } from '@/features/tools-credentials/credential-row'
import { formatMoney } from '@/shared/lib/format'
import { Badge, Button, Card, CostMeter, Divider, Icon, toast } from '@/shared/ui'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

const technicalQuestion: Question = {
  id: 'tq-demo',
  project_id: 'demo',
  code: 'TQ-2',
  kind: 'budget_reached',
  severity: 'major',
  status: 'open',
  text: 'Бюджет прогона $10 исчерпан на этапе сверки вопросов. Потрачено $10,12.',
  assumption: '',
  element_ids: [],
  category: 'technical',
  blocking: true,
  actions: [
    { kind: 'raise_budget', label: 'Поднять бюджет' },
    { kind: 'retry', label: 'Повторить' },
    { kind: 'continue_without', label: 'Продолжить без этого' },
    { kind: 'open_settings', label: 'Открыть настройки' },
  ],
  created_at: '2026-11-04T10:00:00Z',
  updated_at: '2026-11-04T10:00:00Z',
}

const capabilityReady: CapabilityCard = {
  capability: 'speech_to_text',
  label: 'Распознавание речи',
  description: 'Расшифровка голосовых заметок, аудио и видео со звуком.',
  tool: 'transcribe',
  keys: 1,
  kinds: ['speech_to_text'],
  providers: [
    { id: 'deepgram', label: 'Deepgram' },
    { id: 'openai', label: 'OpenAI' },
  ],
  available: true,
  last_error_code: null,
}

const capabilityEmpty: CapabilityCard = {
  capability: 'ocr',
  label: 'Распознавание текста',
  description: 'Текст со сканов PDF, которые не прочитались сами.',
  tool: 'ocr_pages',
  keys: 0,
  kinds: ['ocr'],
  providers: [
    { id: 'mistral', label: 'Mistral OCR' },
    { id: 'yandex', label: 'Yandex Vision OCR' },
  ],
  available: false,
  last_error_code: null,
}

const credential: Credential = {
  id: 'demo-credential',
  label: 'Рабочий Deepgram',
  provider: 'deepgram',
  kinds: ['speech_to_text'],
  capabilities: ['speech_to_text'],
  priority: 10,
  enabled: true,
  is_default: false,
  base_url: null,
  default_model: null,
  key_hint: 'abcd',
  monthly_limit: { minutes: 40 },
  exhausted_until: null,
  last_error: null,
  last_error_code: null,
  last_used_at: '2026-11-04T09:00:00Z',
  created_at: '2026-11-04T08:00:00Z',
}

/** Оценка до запуска: диапазон и разбивка на статичных данных (сервер не нужен). */
function EstimateDemo() {
  return (
    <div className="flex w-full flex-col gap-3">
      <CostMeter label="Стоимость" estimate={{ min: 1.8, max: 3.2 }} budget={10} />
      <div className="flex flex-wrap gap-x-4 gap-y-1 type-caption text-fg-muted" data-numeric>
        <span className="flex items-center gap-1.5">
          <Icon name="clock" size={14} className="text-fg-subtle" />
          1–3 мин
        </span>
        <span className="flex items-center gap-1.5">
          <Icon name="list-check" size={14} className="text-fg-subtle" />
          8–12 запросов
        </span>
        <span className="flex items-center gap-1.5">
          <Icon name="notes" size={14} className="text-fg-subtle" />
          120–180 тыс. токенов
        </span>
      </div>
      <Divider />
      <ul className="flex flex-col gap-1.5">
        {[
          ['Чтение источников', '2 запроса', '$0,2–0,4'],
          ['Сверка вопросов', '6–8 запросов', '$1,2–2,4'],
          ['Сборка схемы', '2 запроса', '$0,4–0,4'],
        ].map(([label, calls, cost]) => (
          <li key={label} className="flex items-baseline justify-between gap-3">
            <span className="type-caption text-fg">{label}</span>
            <span className="type-caption text-fg-subtle" data-numeric>
              {calls}
              {' \u00B7 '}
              {cost}
            </span>
          </li>
        ))}
      </ul>
      <Badge tone="amber" variant="outline" icon="alert-triangle">
        Неполная оценка: не у всех шагов известны цены
      </Badge>
    </div>
  )
}

/** Ожидание прогона: карточка с бюджетом и кнопкой продолжения. */
function WaitingDemo() {
  return (
    <Card variant="elevated" padding="sm" className="flex w-full flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="grid size-6 place-items-center rounded-md bg-amber-subtle text-amber-fg">
          <Icon name="clock" size={14} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="type-subheading text-fg">Ждёт вашего действия</span>
          <span className="type-caption text-fg-subtle">Ответьте на технический вопрос</span>
        </div>
        <Button size="sm" variant="primary" onClick={() => toast('Действие в образце')}>
          Продолжить
        </Button>
      </div>
      <div className="rounded-md bg-amber-subtle px-3 py-2.5 type-caption text-amber-fg">
        Прогон остановился на техническом вопросе. Ответьте на него в панели вопросов или продолжите
        без него: работа начнётся заново с первого этапа, потраченное останется.
      </div>
      <CostMeter label="Стоимость" spent={2.71} budget={10} />
    </Card>
  )
}

function CredentialDemo() {
  const [enabled, setEnabled] = useState(true)
  return (
    <CredentialRow
      credential={{ ...credential, enabled }}
      providers={[{ id: 'deepgram', label: 'Deepgram' }]}
      checking={false}
      onCheck={() => toast('Проверить ключ')}
      onEdit={() => toast('Изменить ключ')}
      onToggle={setEnabled}
      onDelete={() => toast('Удалить ключ')}
    />
  )
}

/** Паттерны волны 2: оценка и бюджет, стоимость и ожидание, технические вопросы, инструменты. */
export function WaveTwoSection() {
  return (
    <Section
      id="wave2"
      eyebrow="24 Волна 2"
      title="Оценка, технические вопросы и инструменты"
      lead="Прогон начинается с оценки: диапазон цены и времени, бюджет и разбивка по этапам. Блокирующий технический вопрос останавливает прогон и спрашивает действие, а ключи инструментов настраиваются по типам задач."
    >
      <SpecimenGrid>
        <Specimen title="Оценка до запуска" note="CostMeter, диапазон и разбивка">
          <EstimateDemo />
        </Specimen>
        <Specimen title="Ожидание прогона" note="waiting, «Продолжить»">
          <WaitingDemo />
        </Specimen>
        <Specimen title="Технический вопрос" note="TechnicalQuestionCard, действия">
          <div className="flex w-full flex-col gap-3">
            <TechnicalQuestionCard
              question={technicalQuestion}
              onAction={(kind) => toast(`Действие: ${kind}`)}
            />
            <Caption>
              Блокирующий вопрос держит прогон в ожидании. Действия — вместо текстового ответа;
              «Открыть настройки» уводит в раздел инструментов.
            </Caption>
          </div>
        </Specimen>
        <Specimen title="Ключи инструментов" note="CapabilityCardView, CredentialRow">
          <div className="flex w-full flex-col gap-3">
            <CapabilityCardView card={capabilityReady} onAdd={() => toast('Добавить ключ')} />
            <CapabilityCardView card={capabilityEmpty} onAdd={() => toast('Добавить ключ')} />
            <CredentialDemo />
            <Caption>
              Ключ закрывает один или несколько типов задач. Приоритет решает, какой ключ пробовать
              первым, лимит на месяц — когда ключ отдохнёт.
            </Caption>
          </div>
        </Specimen>
      </SpecimenGrid>
      <Specimen title="Разбивка стоимости" note="по этапам прогона">
        <ul className="flex w-full max-w-xl flex-col gap-1.5">
          {[
            ['Извлечение', 6, 1.4],
            ['Вопросы', 8, 1.1],
            ['Схема', 2, 0.21],
          ].map(([label, calls, cost]) => (
            <li key={String(label)} className="flex items-baseline justify-between gap-3">
              <span className="type-caption text-fg-muted">{label}</span>
              <span className="type-caption text-fg-subtle" data-numeric>
                {calls} вызовов{' \u00B7 '}
                {formatMoney(Number(cost))}
              </span>
            </li>
          ))}
        </ul>
      </Specimen>
    </Section>
  )
}
