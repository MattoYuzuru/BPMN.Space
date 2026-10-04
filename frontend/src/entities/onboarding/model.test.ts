import { CHECKLIST_ITEMS, type ChecklistItemKey } from './items'
import {
  checklistProgress,
  completedKeys,
  isChecklistVisible,
  isItemDone,
  isOnboardingEnabled,
  isTourActive,
  type OnboardingState,
  shouldOfferTour,
  type TourState,
  withCompletedItem,
} from './model'

const TOUR: TourState = {
  status: 'pending',
  step: null,
  project_id: null,
  updated_at: '2026-10-04T10:00:00Z',
}

function state(patch: Partial<OnboardingState> = {}): OnboardingState {
  return {
    enabled: true,
    tour: TOUR,
    checklist: { hidden: false, items: [] },
    tour_text_suggestion: 'Текст',
    ...patch,
  }
}

const done = (...keys: ChecklistItemKey[]) =>
  state({
    checklist: {
      hidden: false,
      items: keys.map((key) => ({
        key,
        completed_at: '2026-10-04T10:00:00Z',
        source: 'server' as const,
      })),
    },
  })

describe('состояние онбординга', () => {
  it('выключенный онбординг и отсутствие данных — не показываем ничего', () => {
    const disabled: OnboardingState = { enabled: false }
    expect(isOnboardingEnabled(disabled)).toBe(false)
    expect(isOnboardingEnabled(undefined)).toBe(false)
    expect(shouldOfferTour(disabled)).toBe(false)
    expect(isChecklistVisible(disabled)).toBe(false)
    expect(isTourActive(disabled)).toBe(false)
    expect(checklistProgress(disabled)).toEqual({ done: 0, total: 12, complete: false })
  })

  it('приветствие предлагается только пока тур в статусе pending', () => {
    expect(shouldOfferTour(state())).toBe(true)
    for (const status of ['active', 'completed', 'dismissed'] as const) {
      const tour = { status, step: null, project_id: null, updated_at: '' }
      expect(shouldOfferTour(state({ tour }))).toBe(false)
    }
    expect(isTourActive(state({ tour: { ...TOUR, status: 'active' } }))).toBe(true)
  })

  it('прогресс считает отмеченные пункты', () => {
    const progress = checklistProgress(done('project_created', 'voice_added'))
    expect(progress).toEqual({ done: 2, total: 12, complete: false })
    expect(isItemDone(done('voice_added'), 'voice_added')).toBe(true)
    expect(isItemDone(done('voice_added'), 'project_created')).toBe(false)
    expect([...completedKeys(done('voice_added'))]).toEqual(['voice_added'])
  })

  it('плашка видна, пока чек-лист не скрыт и не завершён', () => {
    expect(isChecklistVisible(state())).toBe(true)
    expect(isChecklistVisible(state({ checklist: { hidden: true, items: [] } }))).toBe(false)
    const all = done(...CHECKLIST_ITEMS.map((item) => item.key))
    expect(checklistProgress(all).complete).toBe(true)
    expect(isChecklistVisible(all)).toBe(false)
  })

  it('оптимистичная отметка добавляет пункт один раз', () => {
    const marked = withCompletedItem(state(), 'simulation_run', 'client', '2026-10-04T11:00:00Z')
    expect(marked.checklist?.items).toEqual([
      { key: 'simulation_run', completed_at: '2026-10-04T11:00:00Z', source: 'client' },
    ])
    const again = withCompletedItem(marked, 'simulation_run', 'client', '2026-10-04T12:00:00Z')
    expect(again).toBe(marked)
    expect(withCompletedItem({ enabled: false }, 'simulation_run', 'client', 'x')).toEqual({
      enabled: false,
    })
  })
})
