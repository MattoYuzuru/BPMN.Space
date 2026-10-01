import { useState } from 'react'
import {
  AssumptionFrame,
  Badge,
  Button,
  Card,
  CardHeader,
  FlowLine,
  GridBackdrop,
  SegmentedControl,
  Stepper,
  Tag,
} from '@/shared/ui'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

export function BrandSection() {
  const [flow, setFlow] = useState<'idle' | 'active' | 'done'>('active')
  return (
    <Section
      id="brand"
      eyebrow="09 Фирменные приёмы"
      title="Четыре приёма, по которым узнаётся продукт"
      lead="Каждый приём — переиспользуемый примитив с одним смыслом. Их мало и они тихие: если поставить все четыре на один экран, он станет шумным."
    >
      <SpecimenGrid>
        <Specimen title="Сетка-подложка" note="<GridBackdrop pattern glow />" bodyClassName="p-0">
          <div className="relative isolate grid h-56 place-items-center">
            <GridBackdrop glow />
            <div className="flex flex-col items-center gap-2 text-center">
              <span className="type-heading text-fg">Чертёжная сетка</span>
              <span className="type-caption max-w-xs text-fg-muted">
                Мотив холста BPMN. Под пустыми состояниями и самим холстом, с затуханием к краям.
              </span>
            </div>
          </div>
        </Specimen>

        <Specimen title="Свечение тока" note="shadow-glow, Card glow" canvas>
          <div className="flex h-44 items-center justify-center gap-5">
            <Card variant="elevated" className="w-52">
              <CardHeader title="Прогон 3" description="Вчера, 18:40" icon="history" />
            </Card>
            <Card glow className="w-52">
              <CardHeader title="Прогон 4" description="Выполняется" icon="bolt" />
            </Card>
          </div>
          <p className="type-caption text-fg-muted">
            Мягкий ореол Тока выделяет одну активную вещь на экране: текущий прогон, выбранный
            вопрос. Не больше одного свечения в поле зрения.
          </p>
        </Specimen>

        <Specimen title="Линия тока" note="<FlowLine state />, внутри Stepper и Progress">
          <div className="flex flex-col gap-5">
            <div className="flex items-center gap-3">
              <span className="type-caption w-28 text-fg-subtle">Источники</span>
              <FlowLine state={flow} className="flex-1" />
              <span className="type-caption w-20 text-right text-fg-subtle">Схема</span>
            </div>
            <SegmentedControl
              aria-label="Состояние линии"
              size="sm"
              value={flow}
              onValueChange={setFlow}
              options={[
                { value: 'idle', label: 'Впереди' },
                { value: 'active', label: 'Идёт ток' },
                { value: 'done', label: 'Пройдено' },
              ]}
            />
            <p className="type-caption text-fg-muted">
              Тонкая линия хода процесса. Пока этап выполняется, по ней спокойно бежит импульс —
              видно, что система работает, без спиннера и процентов.
            </p>
          </div>
        </Specimen>

        <Specimen title="Янтарный пунктир" note="<AssumptionFrame />, Tag assumption">
          <div className="flex flex-col gap-4">
            <AssumptionFrame
              actions={
                <Button size="sm" variant="ghost">
                  Уточнить
                </Button>
              }
            >
              Бюджет согласует руководитель отдела.
            </AssumptionFrame>
            <div className="flex flex-wrap items-center gap-2">
              <Caption>На схеме и в списках:</Caption>
              <Tag variant="assumption" icon="assumption">
                Руководитель отдела
              </Tag>
              <Badge tone="amber" icon="assumption">
                3 допущения
              </Badge>
            </div>
            <p className="type-caption text-fg-muted">
              Всё, что система предположила сама, обведено янтарным пунктиром. При наведении пунктир
              медленно течёт: допущение можно уточнить.
            </p>
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}

/** Мини-композиция для шапки витрины: все приёмы в работе. */
export function HeroComposition() {
  return (
    <div className="relative isolate overflow-hidden rounded-xl border border-border bg-bg-subtle p-6">
      <GridBackdrop glow />
      <Card glow padding="md" className="flex flex-col gap-4">
        <CardHeader
          title="Техприсоединение"
          description="Прогон 4, источников 3"
          icon="diagram"
          actions={
            <Badge tone="accent" dot>
              Идёт анализ
            </Badge>
          }
        />
        <Stepper
          aria-label="Ход прогона"
          steps={[
            { id: 'read', title: 'Источники прочитаны', meta: '2 с', status: 'complete' },
            { id: 'ask', title: 'Вопросы сформулированы', meta: '9 с', status: 'complete' },
            {
              id: 'build',
              title: 'Строим схему',
              description: 'Дорожки: Заявитель, Сетевая организация',
              status: 'current',
            },
            { id: 'check', title: 'Проверка XSD и bpmnlint', status: 'upcoming' },
          ]}
        />
        <AssumptionFrame>Срок направления договора: 10 рабочих дней.</AssumptionFrame>
      </Card>
    </div>
  )
}
