import { useState } from 'react'
import { AGENT_STEP_PRESETS } from '@/entities/run'
import { AgentModeHint } from '@/features/onboarding/agent-mode-hint'
import { Badge, Button, Card, Icon, SegmentedControl, Tag } from '@/shared/ui'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

function AgentModeDemo() {
  const [mode, setMode] = useState<'pipeline' | 'agent'>('pipeline')
  const [steps, setSteps] = useState(12)
  return (
    <div className="flex w-full flex-col gap-3">
      <SegmentedControl<'pipeline' | 'agent'>
        aria-label="Режим работы"
        value={mode}
        onValueChange={setMode}
        options={[
          { value: 'pipeline', label: 'Конвейер', icon: 'route' },
          { value: 'agent', label: 'Агентный', icon: 'bolt' },
        ]}
      />
      {mode === 'agent' ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="type-caption text-fg-muted">Лимит шагов</span>
            {AGENT_STEP_PRESETS.map((preset) => (
              <Button
                key={preset}
                size="sm"
                variant={steps === preset ? 'secondary' : 'ghost'}
                onClick={() => setSteps(preset)}
              >
                {preset}
              </Button>
            ))}
            <Tag icon="bolt">агент</Tag>
          </div>
          <AgentModeHint enabled />
        </div>
      ) : (
        <Caption>
          Конвейер идёт по фиксированным этапам: дешевле и предсказуемее. Агентный режим включайте,
          когда материалы сложные и модели нужно самой решать, что читать.
        </Caption>
      )}
    </div>
  )
}

/** Волна 4: агентный режим в диалоге запуска и карточке прогона. */
export function WaveFourSection() {
  return (
    <Section
      id="wave4"
      eyebrow="26 Волна 4"
      title="Агентный режим"
      lead="Модель может сама читать источники инструментами: режим выбирается в диалоге запуска, лимит шагов и бюджет ограничены, а ходы и стоимость видны в карточке прогона."
    >
      <SpecimenGrid>
        <Specimen title="Режим в диалоге запуска" note="SegmentedControl, AgentModeHint">
          <AgentModeDemo />
        </Specimen>
        <Specimen title="Агентный прогон" note="Badge, стоимость и ходы">
          <div className="flex w-full flex-col gap-2">
            <Card variant="outline" padding="sm" className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="type-subheading text-fg">Сборка схемы</span>
                <Badge tone="accent" variant="outline" icon="bolt">
                  Агентный режим
                </Badge>
              </div>
              <span className="type-caption text-fg-muted">
                Прогон идёт по этапам, но чтение источников — инструментами модели.
              </span>
              <span className="flex items-center gap-1.5 type-caption text-fg-muted" data-numeric>
                <Icon name="bolt" size={14} />
                Ходов агента: 3 из 12
              </span>
            </Card>
            <Caption>
              Если сервер выключил агентный режим или модель не умеет инструменты, диалог не даёт
              его выбрать; отказ 422 объясняется рядом с переключателем.
            </Caption>
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
