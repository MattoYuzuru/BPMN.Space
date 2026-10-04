import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  type ChecklistItemKey,
  type OnboardingState,
  onboardingKeys,
  useOnboardingUi,
} from '@/entities/onboarding'
import { sessionKeys } from '@/entities/session'
import { useTourStore } from '@/features/onboarding/tour/store'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { OnboardingWatcher } from './onboarding-watcher'
import { useRecentItems } from './recent'
import { planItemVisit } from './target'
import { presentVisit } from './visit'

const success = vi.fn()
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { success: (...args: unknown[]) => success(...args) }),
}))

const hideHint = vi.fn()
vi.mock('@/features/onboarding/hint', () => ({
  showHint: vi.fn(),
  hideHint: () => hideHint(),
}))

const USER = { id: 'u1', email: 'a@example.com' }

function state(
  keys: ChecklistItemKey[],
  tour: 'active' | 'completed' = 'completed',
): OnboardingState {
  return {
    enabled: true,
    tour: { status: tour, step: null, project_id: null, updated_at: '2026-10-04T10:00:00Z' },
    checklist: {
      hidden: false,
      items: keys.map((key) => ({ key, completed_at: '2026-10-04T10:00:00Z', source: 'server' })),
    },
    tour_text_suggestion: '',
  }
}

const ALL: ChecklistItemKey[] = [
  'project_created',
  'text_source_added',
  'document_uploaded',
  'voice_added',
  'diagram_built',
  'question_answered',
  'assumption_accepted',
  'diagram_rebuilt',
  'diagram_edited',
  'simulation_run',
  'diagram_exported',
  'project_shared',
]

function setup(initial: OnboardingState) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(sessionKeys.all, { auth_enabled: true, user: USER })
  client.setQueryData(onboardingKeys.user(USER.id), initial)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  render(<OnboardingWatcher />, { wrapper })
  const update = (next: OnboardingState) =>
    act(async () => {
      client.setQueryData(onboardingKeys.user(USER.id), next)
      // Подписчики запросов уведомляются через таймер.
      await new Promise((resolve) => setTimeout(resolve, 5))
    })
  return { client, update }
}

afterEach(() => {
  success.mockReset()
  hideHint.mockReset()
  act(() => {
    useTourStore.getState().stop()
    useRecentItems.getState().clear()
    useOnboardingUi.getState().closeChecklist()
  })
})

describe('OnboardingWatcher', () => {
  it('первую загрузку не объявляет', async () => {
    setup(state(['project_created', 'text_source_added']))
    expect(success).not.toHaveBeenCalled()
  })

  it('новый пункт вне тура — «Готово: …» со счётчиком и действием «Открыть»', async () => {
    const { update } = setup(state(['project_created']))
    await update(state(['project_created', 'question_answered']))
    expect(success).toHaveBeenCalledTimes(1)
    const [title, options] = success.mock.calls[0] as [
      string,
      { description: string; action: { label: string; onClick: () => void } },
    ]
    expect(title).toBe('Готово: Ответить на вопрос')
    expect(options.description).toBe('Начало работы — 2 из 12')
    expect(options.action.label).toBe('Открыть')
    options.action.onClick()
    expect(useOnboardingUi.getState().checklistOpen).toBe(true)
  })

  it('несколько сразу — одно сводное уведомление', async () => {
    const { update } = setup(state(['project_created']))
    await update(state(['project_created', 'text_source_added', 'document_uploaded']))
    expect(success).toHaveBeenCalledTimes(1)
    expect(success.mock.calls[0]?.[0]).toBe('Готово: 2 шага')
    await update(state(ALL.slice(0, 8)))
    expect(success.mock.calls[1]?.[0]).toBe('Готово: 5 шагов')
  })

  it('повторный ответ с тем же набором ничего не объявляет', async () => {
    const { update } = setup(state(['project_created']))
    await update(state(['project_created']))
    expect(success).not.toHaveBeenCalled()
  })

  it('во время тура молчит, но отмечает пункт «недавним»', async () => {
    const { update } = setup(state(['project_created'], 'active'))
    await update(state(['project_created', 'text_source_added'], 'active'))
    expect(success).not.toHaveBeenCalled()
    expect(useRecentItems.getState().at.text_source_added).toBeTypeOf('number')
  })

  it('молчит и когда тур закончился в тот же ответ, что принёс отметку его шага', async () => {
    const { update } = setup(state(['project_created'], 'active'))
    await update(state(['project_created', 'project_shared'], 'completed'))
    expect(success).not.toHaveBeenCalled()
  })

  it('после тура снова объявляет', async () => {
    const { update } = setup(state(['project_created'], 'active'))
    await update(state(['project_created'], 'completed'))
    await update(state(['project_created', 'diagram_exported'], 'completed'))
    expect(success).toHaveBeenCalledTimes(1)
  })

  it('идёт запущенный тур в браузере — тоже тишина', async () => {
    const { update } = setup(state(['project_created']))
    act(() => useTourStore.getState().start('project.create'))
    await update(state(['project_created', 'text_source_added']))
    expect(success).not.toHaveBeenCalled()
  })

  it('последний пункт — «Вы освоили Архитектор» без действия', async () => {
    const { update } = setup(state(ALL.slice(0, 11)))
    await update(state(ALL))
    expect(success).toHaveBeenCalledTimes(1)
    expect(success.mock.calls[0]?.[0]).toBe('Вы освоили Архитектор')
    expect(success.mock.calls[0]?.[1]).not.toHaveProperty('action')
  })

  it('подсказка про выполненный пункт закрывается сама', async () => {
    const { update } = setup(state([]))
    presentVisit(
      'diagram_exported',
      planItemVisit('diagram_exported', { route: 'workspace', project_id: 'p', hint: 'do_item' }),
    )
    await update(state(['project_created']))
    // подсказка про другой пункт остаётся
    expect(hideHint).not.toHaveBeenCalled()
    await update(state(['project_created', 'diagram_exported']))
    expect(hideHint).toHaveBeenCalledOnce()
  })

  it('сигнал run.finished перечитывает состояние онбординга', async () => {
    const { client } = setup(state([]))
    const spy = vi.spyOn(client, 'invalidateQueries')
    act(() =>
      emitOnboardingSignal({
        type: 'run.finished',
        status: 'succeeded',
        openQuestions: 2,
        hasDiagram: true,
        projectId: 'p1',
      }),
    )
    expect(spy).toHaveBeenCalledWith({ queryKey: onboardingKeys.all })
  })

  it('другой пользователь: его первый ответ не объявляется', async () => {
    const { client, update } = setup(state(['project_created']))
    await act(async () => {
      client.setQueryData(sessionKeys.all, {
        auth_enabled: true,
        user: { id: 'u2', email: 'b@example.com' },
      })
      client.setQueryData(
        onboardingKeys.user('u2'),
        state(['project_created', 'text_source_added']),
      )
      await new Promise((resolve) => setTimeout(resolve, 5))
    })
    expect(success).not.toHaveBeenCalled()
    await act(async () => {
      client.setQueryData(
        onboardingKeys.user('u2'),
        state(['project_created', 'text_source_added', 'voice_added']),
      )
      await new Promise((resolve) => setTimeout(resolve, 5))
    })
    expect(success).toHaveBeenCalledTimes(1)
    void update
  })

  it('финал во время тура объявляется, когда тур закончился', async () => {
    const { update } = setup(state(ALL.slice(0, 11), 'active'))
    await update(state(ALL, 'active'))
    expect(success).not.toHaveBeenCalled()
    await update(state(ALL, 'completed'))
    expect(success).toHaveBeenCalledTimes(1)
    expect(success.mock.calls[0]?.[0]).toBe('Вы освоили Архитектор')
  })

  it('успешная мутация перечитывает состояние, помеченная skipOnboarding — нет', async () => {
    const { client } = setup(state([]))
    const spy = vi.spyOn(client, 'invalidateQueries')
    await act(async () => {
      await client
        .getMutationCache()
        .build(client, { mutationFn: async () => 'ok' })
        .execute(undefined)
    })
    expect(spy).toHaveBeenCalledWith({ queryKey: onboardingKeys.all })
    spy.mockClear()
    await act(async () => {
      await client
        .getMutationCache()
        .build(client, { mutationFn: async () => 'ok', meta: { skipOnboarding: true } })
        .execute(undefined)
    })
    expect(spy).not.toHaveBeenCalled()
  })
})
