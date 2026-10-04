import {
  type ChecklistItemKey,
  useChecklistView,
  useOnboardingUi,
  useRestartTour,
  useSetChecklistHidden,
} from '@/entities/onboarding'
import { startTour, useTourStore } from '@/features/onboarding/tour/store'
import { Button, Sheet, SheetContent } from '@/shared/ui'
import { ChecklistBody } from './checklist-panel'
import { useVisitItem } from './visit'

/** Шаг, с которого начинается тур (совпадает с `TourStepKey` бэкенда). */
const TOUR_FIRST_STEP = 'project.create'

/** Кнопки внизу панели: повторить обучение и скрыть плашку. */
export function ChecklistFooter({
  tourActive,
  complete,
  hidden,
  busy,
  onTour,
  onToggleHidden,
}: {
  tourActive: boolean
  complete: boolean
  hidden: boolean
  busy?: boolean
  onTour: () => void
  onToggleHidden: () => void
}) {
  return (
    <div className="flex w-full items-center justify-between gap-2">
      <Button variant="secondary" loading={busy} onClick={onTour}>
        {tourActive ? 'Продолжить обучение' : 'Пройти обучение заново'}
      </Button>
      {!complete && (
        <Button variant="ghost" onClick={onToggleHidden}>
          {hidden ? 'Показывать прогресс' : 'Скрыть чек-лист'}
        </Button>
      )}
    </div>
  )
}

/** Боковая панель «Начало работы»: открывается через `useOnboardingUi`, грузится лениво. */
export default function ChecklistSheet() {
  const open = useOnboardingUi((state) => state.checklistOpen)
  const close = useOnboardingUi((state) => state.closeChecklist)
  const view = useChecklistView()
  const restart = useRestartTour()
  const setHidden = useSetChecklistHidden()
  const { visit, pending } = useVisitItem()
  const tourRunning = useTourStore((state) => state.status === 'active')
  const locked = view.tourActive || tourRunning

  const onTour = () => {
    if (locked) {
      // Тур уже идёт: панель закрываем; если он на паузе (ушли с экрана шага) — возвращаем.
      close()
      if (useTourStore.getState().paused) useTourStore.getState().setPaused(false)
      return
    }
    restart.mutate(undefined, {
      onSuccess: () => {
        close()
        startTour(TOUR_FIRST_STEP)
      },
    })
  }

  return (
    <Sheet open={open} onOpenChange={(next) => !next && close()}>
      <SheetContent
        size="sm"
        title="Начало работы"
        footer={
          <ChecklistFooter
            tourActive={locked}
            complete={view.complete}
            hidden={view.hidden}
            busy={restart.isPending}
            onTour={onTour}
            onToggleHidden={() => setHidden.mutate(!view.hidden)}
          />
        }
      >
        <ChecklistBody
          doneKeys={view.doneKeys}
          locked={locked}
          pending={pending}
          onVisit={(item: ChecklistItemKey) => void visit(item)}
        />
      </SheetContent>
    </Sheet>
  )
}
