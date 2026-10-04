/**
 * Демо-тур витрины: четыре шага по элементам стайлгайда — рассказ, действие, элемент внутри
 * модального окна и якорь, которого нет. Показывает движок обучения целиком, без бэкенда.
 */
import type { TourPersistence, TourStep } from '@/features/onboarding/tour'

export const DEMO_ANCHORS = {
  story: 'styleguide.demo.story',
  action: 'styleguide.demo.action',
  dialog: 'styleguide.demo.dialog',
  missing: 'styleguide.demo.missing',
} as const

export const DEMO_DIALOG = 'tour-demo'

export const demoSteps: TourStep<null>[] = [
  {
    key: 'story',
    chapter: 'demo',
    title: 'Рассказ',
    kind: 'story',
    anchor: DEMO_ANCHORS.story,
    side: 'right',
    pages: [
      { text: 'Рассказ листается кнопками или стрелками. Вырез подсвечивает один элемент.' },
      {
        text: 'Страниц у шага до трёх, точки внизу показывают, где вы. Клик по затемнению вернёт взгляд к карточке.',
      },
    ],
  },
  {
    key: 'action',
    chapter: 'demo',
    title: 'Действие',
    kind: 'action',
    anchor: DEMO_ANCHORS.action,
    side: 'right',
    pages: [
      {
        text: 'Здесь продолжаете вы: нажмите подсвеченную кнопку. Вырез свободен, остальное закрыто.',
      },
    ],
    until: (signal) => signal.type === 'dialog.opened' && signal.name === DEMO_DIALOG,
  },
  {
    key: 'dialog',
    chapter: 'demo',
    title: 'Элемент в окне',
    kind: 'story',
    anchor: DEMO_ANCHORS.dialog,
    side: 'bottom',
    pages: [
      {
        text: 'Якорь внутри окна: своего затемнения тур не рисует, а карточка живёт внутри окна и не закрывает его.',
      },
    ],
  },
  {
    key: 'missing',
    chapter: null,
    title: 'Якорь не найден',
    kind: 'finish',
    anchor: DEMO_ANCHORS.missing,
    pages: [
      {
        text: 'Элемента нет на экране, и карточка встала по центру. У шага-действия тур продолжил бы ждать сигнал.',
      },
    ],
  },
]

/** Хранилище демо-тура: ничего не отправляет, только сообщает о вызовах. */
export function createDemoPersistence(log: (line: string) => void): TourPersistence {
  return {
    load: async () => ({ status: 'pending', step: null }),
    saveStep: (step) => {
      log(`saveStep("${step}")`)
      return Promise.resolve()
    },
    setStatus: (status) => {
      log(`setStatus("${status}")`)
      return Promise.resolve()
    },
  }
}
