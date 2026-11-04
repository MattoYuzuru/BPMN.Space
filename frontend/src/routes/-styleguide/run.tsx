import { useState } from 'react'
import { Card, CostMeter, Slider, Switch } from '@/shared/ui'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

function SliderDemo() {
  const [value, setValue] = useState(64)
  return (
    <div className="flex w-full flex-col gap-5">
      <Slider
        label="Длительность записи"
        value={value}
        showValue
        formatValue={(current) => `${current} %`}
        onValueChange={setValue}
      />
      <Slider label="Уровень сигнала" value={30} disabled />
      <Caption>
        Стрелки двигают бегунок, Home/End — к краям шкалы. Выключенный не реагирует.
      </Caption>
    </div>
  )
}

export function RunSection() {
  return (
    <Section
      id="run"
      eyebrow="23 Прогон"
      title="Стоимость и бюджет"
      lead="Оценка до запуска — диапазон, а не одно число: у модели есть цены на токены и кеш, но часть шагов может остаться без цены. Бюджет задаёт потолок, и превышение всегда видно до запуска. Во время прогона на месте оценки показывается потраченное."
    >
      <SpecimenGrid>
        <Specimen title="CostMeter" note="оценка, бюджет, потраченное">
          <div className="flex w-full flex-col gap-6">
            <CostMeter label="Оценка прогона" estimate={{ min: 1.8, max: 3.2 }} budget={10} />
            <CostMeter label="Потрачено" spent={2.71} budget={10} />
            <CostMeter label="Превышение" spent={12.4} budget={10} />
            <CostMeter
              label="Неполная оценка"
              estimate={{ min: 0.9, max: 1.4 }}
              budget={5}
              incomplete
            />
            <CostMeter label="Без бюджета" estimate={{ min: 0.04, max: 0.12 }} />
          </div>
        </Specimen>
        <Specimen title="Слайдер" note="Slider, Radix">
          <SliderDemo />
        </Specimen>
        <Specimen title="Бюджет в шапке прогона" note="карточка, Switch">
          <Card variant="outline" padding="md" className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <span className="type-ui text-fg">Останавливать прогон при превышении</span>
              <Switch defaultChecked aria-label="Останавливать прогон при превышении" />
            </div>
            <CostMeter label="Бюджет" spent={2.71} budget={10} />
          </Card>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
