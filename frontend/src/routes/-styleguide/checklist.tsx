import { useState } from 'react'
import { CHECKLIST_ITEMS, CHECKLIST_TOTAL, type ChecklistItemKey } from '@/entities/onboarding'
import { AccountMenuFor, ChecklistMenuItemView } from '@/features/account-menu/account-menu'
import {
  Button,
  Card,
  DoneMark,
  ProgressRing,
  SegmentedControl,
  Sheet,
  SheetContent,
  SheetTrigger,
} from '@/shared/ui'
import { ChecklistBody } from '@/widgets/onboarding-checklist/checklist-panel'
import { ChecklistFooter } from '@/widgets/onboarding-checklist/checklist-sheet'
import { OnboardingPillView } from '@/widgets/onboarding-pill/onboarding-pill'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

const DEMO_USER = { id: 'demo', email: 'anna.petrova@company.ru' }

/** Первые `count` пунктов по порядку показа. */
const firstKeys = (count: number): Set<ChecklistItemKey> =>
  new Set(CHECKLIST_ITEMS.slice(0, count).map((item) => item.key))

const STATES = [
  { value: '0', label: '0/12' },
  { value: '5', label: '5/12' },
  { value: '12', label: '12/12' },
] as const

type StateValue = (typeof STATES)[number]['value']

/** Меню аккаунта с пунктом «Начало работы» в трёх состояниях: живые, открываются по клику. */
function MenuDemo() {
  return (
    <div className="flex flex-wrap items-start gap-8">
      {STATES.map((state) => (
        <div key={state.value} className="flex flex-col items-center gap-2">
          <AccountMenuFor
            user={DEMO_USER}
            onLogout={() => {}}
            checklist={<ChecklistMenuItemView done={Number(state.value)} onSelect={() => {}} />}
          />
          <span className="type-caption text-fg-subtle" data-numeric>
            {state.label}
          </span>
        </div>
      ))}
    </div>
  )
}

/** Панель с переключаемым состоянием, подсказкой «Доступно после обучения» и живой отметкой. */
function PanelDemo() {
  const [state, setState] = useState<StateValue | 'tour'>('5')
  const [extra, setExtra] = useState<ChecklistItemKey | null>(null)
  const count = state === 'tour' ? 3 : Number(state)
  const doneKeys = firstKeys(count)
  if (extra && state !== 'tour') doneKeys.add(extra)
  const next = CHECKLIST_ITEMS.find((item) => !doneKeys.has(item.key))
  const recentAt = extra ? { [extra]: Date.now() } : {}

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl
          aria-label="Состояние чек-листа"
          size="sm"
          options={[...STATES, { value: 'tour', label: 'Идёт тур' }]}
          value={state}
          onValueChange={(value) => {
            setState(value as StateValue | 'tour')
            setExtra(null)
          }}
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={!next || state === 'tour'}
          onClick={() => next && setExtra(next.key)}
        >
          Отметить следующий пункт
        </Button>
        <span className="type-caption text-fg-subtle">
          Только что отмеченный пункт проявляет галочку и зачёркивание за 320 мс.
        </span>
      </div>
      <Card variant="elevated" padding="none" className="w-full max-w-[23.75rem]">
        <div className="border-b border-border px-5 pt-4 pb-3.5">
          <h3 className="type-heading text-fg">Начало работы</h3>
        </div>
        <div className="px-5 py-4">
          <ChecklistBody
            doneKeys={doneKeys}
            locked={state === 'tour'}
            recentAt={recentAt}
            onVisit={() => {}}
          />
        </div>
        <div className="flex border-t border-border px-5 py-3.5">
          <ChecklistFooter
            tourActive={state === 'tour'}
            complete={doneKeys.size >= CHECKLIST_TOTAL}
            hidden={false}
            onTour={() => {}}
            onToggleHidden={() => {}}
          />
        </div>
      </Card>
    </div>
  )
}

/** Настоящая боковая панель с демо-данными. */
function SheetDemo() {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="secondary" leadingIcon="list-check">
          Открыть панель
        </Button>
      </SheetTrigger>
      <SheetContent
        size="sm"
        title="Начало работы"
        footer={
          <ChecklistFooter
            tourActive={false}
            complete={false}
            hidden={false}
            onTour={() => {}}
            onToggleHidden={() => {}}
          />
        }
      >
        <ChecklistBody doneKeys={firstKeys(5)} recentAt={{}} onVisit={() => {}} />
      </SheetContent>
    </Sheet>
  )
}

/** Чек-лист «Начало работы»: пункт меню, плашка, панель, кольцо прогресса и отметка. */
export function ChecklistSection() {
  return (
    <Section
      id="checklist"
      eyebrow="21 Начало работы"
      title="Чек-лист «Начало работы»"
      lead="Двенадцать первых действий в продукте. Пункт отмечает система, когда пользователь впервые сделал действие, — вручную отметить нельзя. Прогресс виден в меню аккаунта и на плашке внизу слева на экране проектов."
    >
      <SpecimenGrid>
        <Specimen
          title="Пункт меню аккаунта"
          note="между почтой и «Выйти»; при 12/12 кольцо зелёное с галочкой"
        >
          <MenuDemo />
        </Specimen>
        <Specimen
          title="Плашка прогресса"
          note="fixed, внизу слева, только на экране проектов"
          canvas
        >
          <div className="flex flex-wrap items-center gap-4">
            <OnboardingPillView done={0} onClick={() => {}} />
            <OnboardingPillView done={5} onClick={() => {}} />
          </div>
          <p className="mt-4 type-caption text-fg-subtle">
            Видна, пока чек-лист не скрыт и не завершён, тур не идёт и нет открытого окна.
            Появляется мягко (прозрачность и сдвиг на 8 px), после финала тура — с задержкой в
            секунду.
          </p>
        </Specimen>
      </SpecimenGrid>
      <SpecimenGrid>
        <Specimen
          title="ProgressRing"
          note="здесь 28 px (в меню и плашке — 18); дуга растёт за 320 мс"
        >
          <div className="flex flex-wrap items-center gap-6">
            {[0, 5, 9, 12].map((value) => (
              <div key={value} className="flex flex-col items-center gap-2">
                <ProgressRing value={value} max={CHECKLIST_TOTAL} size={28} />
                <span className="type-caption text-fg-subtle" data-numeric>
                  {value}/{CHECKLIST_TOTAL}
                </span>
              </div>
            ))}
          </div>
        </Specimen>
        <Specimen title="DoneMark" note="круглая отметка, не флажок: не принимает ввод">
          <div className="flex flex-wrap items-center gap-6">
            <div className="flex flex-col items-center gap-2">
              <DoneMark done={false} />
              <Caption>не выполнено</Caption>
            </div>
            <div className="flex flex-col items-center gap-2">
              <DoneMark done />
              <Caption>выполнено</Caption>
            </div>
          </div>
        </Specimen>
      </SpecimenGrid>
      <Specimen
        title="Панель «Начало работы»"
        note="SheetContent size=sm; невыполненная строка кликабельна, стрелка при наведении"
      >
        <PanelDemo />
      </Specimen>
      <Specimen title="В боковой панели" note="так панель открывается в продукте">
        <SheetDemo />
      </Specimen>
    </Section>
  )
}
