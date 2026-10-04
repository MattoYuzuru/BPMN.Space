import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { Button, Dialog, DialogContent } from '@/shared/ui'
import { renderUi } from '@/test/render'
import { startTour, stopTour, useTourStore } from './store'
import TourHost from './tour-host'
import type { TourPersistence, TourStep } from './types'

const steps: TourStep<null>[] = [
  {
    key: 'one',
    chapter: 'main',
    title: 'Первый шаг',
    kind: 'story',
    anchor: 'a1',
    pages: [{ text: 'Страница один.' }, { text: 'Страница два.' }],
  },
  {
    key: 'two',
    chapter: 'main',
    title: 'Второй шаг',
    kind: 'action',
    anchor: 'a2',
    pages: [{ text: 'Нажмите кнопку.' }],
    until: (signal) => signal.type === 'share.created',
  },
  {
    key: 'three',
    chapter: 'main',
    title: 'Третий шаг',
    kind: 'action',
    anchor: 'missing',
    pages: [{ text: 'Сделайте действие.' }],
    until: (signal) => signal.type === 'source.added',
  },
  {
    key: 'four',
    chapter: null,
    title: 'Финал',
    kind: 'finish',
    pages: [{ text: 'Готово.' }],
  },
]

function makePersistence(
  remote: { status: 'pending' | 'active'; step: string | null } = { status: 'pending', step: null },
) {
  return {
    load: vi.fn().mockResolvedValue(remote),
    saveStep: vi.fn().mockResolvedValue(undefined),
    setStatus: vi.fn().mockResolvedValue(undefined),
  } satisfies TourPersistence
}

function Page() {
  return (
    <div>
      <Button data-tour="a1">Кнопка A</Button>
      <Button data-tour="a2">Кнопка B</Button>
    </div>
  )
}

function Host({
  persistence,
  onEnd,
  restore = false,
}: {
  persistence: TourPersistence
  onEnd?: () => void
  restore?: boolean
}) {
  return (
    <TourHost
      steps={steps}
      context={null}
      persistence={persistence}
      chapters={{ main: 'Глава' }}
      anchorTimeoutMs={120}
      onEnd={onEnd}
      restore={restore}
    />
  )
}

beforeEach(() => {
  stopTour()
})
afterEach(() => {
  act(() => stopTour())
})

describe('TourHost', () => {
  it('показывает карточку с подписью главы и шага, сохраняет шаг и статус', async () => {
    const persistence = makePersistence()
    renderUi(
      <>
        <Page />
        <Host persistence={persistence} />
      </>,
    )
    act(() => startTour('one'))
    const card = await screen.findByRole('dialog', { name: 'Первый шаг' })
    expect(card).toHaveTextContent('Глава · Шаг 1 из 4')
    expect(card).toHaveTextContent('Страница один.')
    expect(persistence.setStatus).toHaveBeenCalledWith('active')
    expect(persistence.saveStep).toHaveBeenCalledWith('one')
    // фокус на заголовке карточки
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Первый шаг' })).toHaveFocus())
  })

  it('«Далее» листает страницы и переходит к шагу, шаг сохраняется', async () => {
    const persistence = makePersistence()
    const { user } = renderUi(
      <>
        <Page />
        <Host persistence={persistence} />
      </>,
    )
    act(() => startTour('one'))
    await screen.findByRole('dialog', { name: 'Первый шаг' })
    expect(screen.queryByRole('button', { name: 'Назад' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Далее' }))
    expect(await screen.findByText('Страница два.', { selector: '[aria-live]' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Назад' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Далее' }))
    await screen.findByRole('dialog', { name: 'Второй шаг' })
    expect(persistence.saveStep).toHaveBeenLastCalledWith('two')
    // у шага-действия «Назад» нет, есть «Пропустить шаг»
    expect(screen.queryByRole('button', { name: 'Назад' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Пропустить шаг' })).toBeInTheDocument()
  })

  it('шаг-действие продолжается по сигналу из приложения', async () => {
    renderUi(
      <>
        <Page />
        <Host persistence={makePersistence()} />
      </>,
    )
    act(() => startTour('two'))
    await screen.findByRole('dialog', { name: 'Второй шаг' })
    act(() => emitOnboardingSignal({ type: 'source.added', kind: 'text' }))
    expect(screen.getByRole('dialog', { name: 'Второй шаг' })).toBeInTheDocument()
    act(() => emitOnboardingSignal({ type: 'share.created' }))
    expect(useTourStore.getState().stepKey).toBe('three')
    expect(await screen.findByRole('dialog', { name: 'Третий шаг' })).toBeInTheDocument()
  })

  it('якорь не найден: карточка по центру, ожидание сигнала продолжается', async () => {
    renderUi(
      <>
        <Page />
        <Host persistence={makePersistence()} />
      </>,
    )
    act(() => startTour('three'))
    // пока ждём — затемнение есть, карточки нет
    expect(screen.queryByRole('dialog', { name: 'Третий шаг' })).not.toBeInTheDocument()
    const card = await screen.findByRole('dialog', { name: 'Третий шаг' })
    expect(card).toHaveTextContent('Сделайте действие.')
    expect(within(card).getByRole('button', { name: 'Пропустить шаг' })).toBeInTheDocument()
    // шаг-действие без якоря не запирает экран: перехватчиков кликов нет
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(0)
    // шаг-действие без якоря не запирает экран: перехватчиков кликов нет
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(0)
    // действие не пропускается молча: шаг идёт, пока не придёт сигнал
    expect(useTourStore.getState().stepKey).toBe('three')
    act(() => emitOnboardingSignal({ type: 'source.added', kind: 'voice' }))
    expect(useTourStore.getState().stepKey).toBe('four')
  })

  it('вырез блокирует клики вокруг', async () => {
    renderUi(
      <>
        <Page />
        <Host persistence={makePersistence()} />
      </>,
    )
    act(() => startTour('two'))
    await screen.findByRole('dialog', { name: 'Второй шаг' })
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(4)
  })

  it('Esc показывает подтверждение внутри карточки; «Завершить» завершает тур', async () => {
    const persistence = makePersistence()
    const onEnd = vi.fn()
    const { user } = renderUi(
      <>
        <Page />
        <Host persistence={persistence} onEnd={onEnd} />
      </>,
    )
    act(() => startTour('one'))
    await screen.findByRole('dialog', { name: 'Первый шаг' })
    await user.keyboard('{Escape}')
    expect(await screen.findByRole('heading', { name: 'Завершить обучение?' })).toBeInTheDocument()
    // Esc ещё раз — «Продолжить»
    await user.keyboard('{Escape}')
    expect(await screen.findByRole('heading', { name: 'Первый шаг' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Завершить обучение' }))
    await user.click(await screen.findByRole('button', { name: 'Завершить' }))
    expect(persistence.setStatus).toHaveBeenLastCalledWith('dismissed')
    expect(onEnd).toHaveBeenCalledWith('dismissed')
    expect(useTourStore.getState().status).toBe('idle')
  })

  it('восстанавливает шаг с сервера и не пишет его обратно', async () => {
    const persistence = makePersistence({ status: 'active', step: 'two' })
    renderUi(
      <>
        <Page />
        <Host persistence={persistence} restore />
      </>,
    )
    await screen.findByRole('dialog', { name: 'Второй шаг' })
    expect(persistence.load).toHaveBeenCalledOnce()
    expect(persistence.saveStep).not.toHaveBeenCalled()
    expect(persistence.setStatus).not.toHaveBeenCalledWith('active')
  })

  it('не восстанавливает тур, если на сервере он не активен', async () => {
    const persistence = makePersistence({ status: 'pending', step: null })
    renderUi(
      <>
        <Page />
        <Host persistence={persistence} restore />
      </>,
    )
    await waitFor(() => expect(persistence.load).toHaveBeenCalled())
    expect(useTourStore.getState().status).toBe('idle')
  })

  it('финальный шаг по центру: «Готово» завершает тур как пройденный', async () => {
    const persistence = makePersistence()
    const onEnd = vi.fn()
    const { user } = renderUi(
      <>
        <Page />
        <Host persistence={persistence} onEnd={onEnd} />
      </>,
    )
    act(() => startTour('four'))
    await user.click(await screen.findByRole('button', { name: 'Готово' }))
    expect(persistence.setStatus).toHaveBeenLastCalledWith('completed')
    expect(onEnd).toHaveBeenCalledWith('completed')
  })

  it('без тура не создаёт наблюдателей', () => {
    const mutation = vi.spyOn(MutationObserver.prototype, 'observe')
    renderUi(
      <>
        <Page />
        <Host persistence={makePersistence()} />
      </>,
    )
    expect(mutation).not.toHaveBeenCalled()
    mutation.mockRestore()
  })
})

describe('TourHost внутри модального окна', () => {
  const dialogSteps: TourStep<null>[] = [
    {
      key: 'in-dialog',
      chapter: null,
      title: 'Шаг в окне',
      kind: 'story',
      anchor: 'dialog.button',
      pages: [{ text: 'Кнопка в окне.' }],
    },
    {
      key: 'after',
      chapter: null,
      title: 'После окна',
      kind: 'finish',
      pages: [{ text: 'Дальше.' }],
    },
  ]

  it('карточка внутри диалога кликабельна, фокусируется и не закрывает диалог; Esc — подтверждение', async () => {
    const onOpenChange = vi.fn()
    const { user } = renderUi(
      <>
        <Dialog open onOpenChange={onOpenChange}>
          <DialogContent title="Новый проект">
            <Button data-tour="dialog.button">Создать проект</Button>
          </DialogContent>
        </Dialog>
        <TourHost
          steps={dialogSteps}
          context={null}
          persistence={makePersistence()}
          restore={false}
        />
      </>,
    )
    const dialog = screen.getByRole('dialog', { name: 'Новый проект' })
    act(() => startTour('in-dialog'))
    const card = await screen.findByRole('dialog', { name: 'Шаг в окне' })
    // карточка лежит внутри узла диалога — внутри FocusScope, а не «снаружи»
    expect(dialog).toContainElement(card)
    // затемнение тура не рисуется: у окна своё
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(0)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Шаг в окне' })).toHaveFocus())

    // клик по кнопке карточки: диалог остаётся открытым
    await user.click(within(card).getByRole('button', { name: 'Далее' }))
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Новый проект' })).toBeInTheDocument()
    // финал показан по центру (вне окна), тур продолжился
    expect(useTourStore.getState().stepKey).toBe('after')
  })

  it('Esc вне карточки закрывает окно (карточка не слой Radix) и подтверждение не открывает', async () => {
    const onOpenChange = vi.fn()
    const { user } = renderUi(
      <>
        <Dialog open onOpenChange={onOpenChange}>
          <DialogContent title="Новый проект">
            <Button data-tour="dialog.button">Создать проект</Button>
          </DialogContent>
        </Dialog>
        <TourHost
          steps={dialogSteps}
          context={null}
          persistence={makePersistence()}
          restore={false}
        />
      </>,
    )
    act(() => startTour('in-dialog'))
    await screen.findByRole('dialog', { name: 'Шаг в окне' })
    screen.getByRole('button', { name: 'Создать проект' }).focus()
    await user.keyboard('{Escape}')
    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(screen.queryByRole('heading', { name: 'Завершить обучение?' })).toBeNull()
  })

  it('Esc с фокусом в карточке открывает подтверждение, а диалог остаётся открытым', async () => {
    const onOpenChange = vi.fn()
    const { user } = renderUi(
      <>
        <Dialog open onOpenChange={onOpenChange}>
          <DialogContent title="Новый проект">
            <Button data-tour="dialog.button">Создать проект</Button>
          </DialogContent>
        </Dialog>
        <TourHost
          steps={dialogSteps}
          context={null}
          persistence={makePersistence()}
          restore={false}
        />
      </>,
    )
    act(() => startTour('in-dialog'))
    await screen.findByRole('dialog', { name: 'Шаг в окне' })
    await user.keyboard('{Escape}')
    expect(await screen.findByRole('heading', { name: 'Завершить обучение?' })).toBeInTheDocument()
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Новый проект' })).toBeInTheDocument()
  })

  it('клик по карточке в диалоге не считается кликом снаружи', async () => {
    const onOpenChange = vi.fn()
    const { user } = renderUi(
      <>
        <Dialog open onOpenChange={onOpenChange}>
          <DialogContent title="Новый проект">
            <Button data-tour="dialog.button">Создать проект</Button>
          </DialogContent>
        </Dialog>
        <TourHost
          steps={dialogSteps}
          context={null}
          persistence={makePersistence()}
          restore={false}
        />
      </>,
    )
    act(() => startTour('in-dialog'))
    const card = await screen.findByRole('dialog', { name: 'Шаг в окне' })
    await user.click(within(card).getByRole('heading', { name: 'Шаг в окне' }))
    await user.click(within(card).getByRole('button', { name: 'Завершить обучение' }))
    expect(onOpenChange).not.toHaveBeenCalled()
  })
})

describe('TourHost и маршруты', () => {
  it('ставит тур на паузу при уходе с экрана шага и возвращает по кнопке', async () => {
    const routedSteps: TourStep<null>[] = [
      {
        key: 'routed',
        chapter: null,
        title: 'Шаг на экране A',
        kind: 'story',
        anchor: 'on-a',
        route: () => ({ to: '/a' }),
        pages: [{ text: 'Текст.' }],
      },
    ]
    const root = createRootRoute({
      component: () => (
        <>
          <Outlet />
          <TourHost
            steps={routedSteps}
            context={null}
            persistence={makePersistence()}
            restore={false}
          />
        </>
      ),
    })
    const a = createRoute({
      getParentRoute: () => root,
      path: '/a',
      component: () => <div data-tour="on-a">Экран A</div>,
    })
    const b = createRoute({
      getParentRoute: () => root,
      path: '/b',
      component: () => <div>Экран B</div>,
    })
    const router = createRouter({
      routeTree: root.addChildren([a, b]),
      history: createMemoryHistory({ initialEntries: ['/b'] }),
    })
    const { user } = {
      user: (await import('@testing-library/user-event')).default.setup(),
    }
    render(<RouterProvider router={router} />)
    await screen.findByText('Экран B')

    // тур стартует, экран шага — A: движок сам переходит туда
    act(() => startTour('routed'))
    await screen.findByRole('dialog', { name: 'Шаг на экране A' })
    expect(router.state.location.pathname).toBe('/a')

    // пользователь сам ушёл на другой экран: пауза и пилюля
    await act(async () => {
      await router.navigate({ to: '/b' } as never)
    })
    const pill = await screen.findByRole(
      'region',
      { name: 'Обучение приостановлено' },
      { timeout: 2000 },
    )
    expect(useTourStore.getState().paused).toBe(true)
    expect(screen.queryByRole('dialog', { name: 'Шаг на экране A' })).not.toBeInTheDocument()

    // возврат — на экран текущего шага
    await user.click(within(pill).getByRole('button', { name: 'Вернуться к обучению' }))
    await screen.findByRole('dialog', { name: 'Шаг на экране A' })
    expect(router.state.location.pathname).toBe('/a')
    expect(useTourStore.getState().paused).toBe(false)
  })
})
