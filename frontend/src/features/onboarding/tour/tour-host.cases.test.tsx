import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type ReactNode, useEffect, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import {
  Button,
  Dialog,
  DialogContent,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Sheet,
  SheetContent,
} from '@/shared/ui'
import { renderUi } from '@/test/render'
import { startTour, stopTour, useTourStore } from './store'
import TourHost from './tour-host'
import type { CoachPage, TourPersistence, TourStep } from './types'

function persistence(): TourPersistence {
  return {
    load: vi.fn().mockResolvedValue({ status: 'pending', step: null }),
    saveStep: vi.fn().mockResolvedValue(undefined),
    setStatus: vi.fn().mockResolvedValue(undefined),
  }
}

const base: { chapter: null; pages: CoachPage[] } = { chapter: null, pages: [{ text: 'Текст.' }] }

function mount<Ctx>(steps: TourStep<Ctx>[], context: Ctx, extra?: ReactNode) {
  return renderUi(
    <>
      {extra}
      <TourHost
        steps={steps}
        context={context}
        persistence={persistence()}
        restore={false}
        anchorTimeoutMs={150}
      />
    </>,
  )
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

beforeEach(() => stopTour())
afterEach(() => act(() => stopTour()))

/** Появляется через 60 мс после входа в шаг `b`. */
function LateAnchor() {
  const [show, setShow] = useState(false)
  const key = useTourStore((s) => s.stepKey)
  useEffect(() => {
    if (key !== 'b') return
    const timer = setTimeout(() => setShow(true), 60)
    return () => clearTimeout(timer)
  }, [key])
  return show ? <Button data-tour="later">Поздний</Button> : null
}

describe('ожидание якоря между шагами', () => {
  it('устаревший timedOut прошлого шага не пропускает следующий необязательный', async () => {
    const steps: TourStep<null>[] = [
      { ...base, key: 'a', title: 'A', kind: 'story', anchor: 'nope' },
      { ...base, key: 'b', title: 'B', kind: 'action', optional: true, anchor: 'later' },
      { ...base, key: 'c', title: 'C', kind: 'finish' },
    ]
    const { user } = mount(steps, null, <LateAnchor />)
    act(() => startTour('a'))
    await screen.findByRole('dialog', { name: 'A' })
    await user.click(screen.getByRole('button', { name: 'Далее' }))
    await wait(30)
    expect(useTourStore.getState().stepKey).toBe('b')
    // якорь появился — карточка на нём, шаг не пропущен
    expect(await screen.findByRole('dialog', { name: 'B' })).toBeInTheDocument()
    expect(useTourStore.getState().stepKey).toBe('b')
  })

  it('необязательный шаг без якоря после таймаута пропускается', async () => {
    const steps: TourStep<null>[] = [
      { ...base, key: 'a', title: 'A', kind: 'action', optional: true, anchor: 'nope' },
      { ...base, key: 'c', title: 'C', kind: 'finish' },
    ]
    mount(steps, null)
    act(() => startTour('a'))
    await waitFor(() => expect(useTourStore.getState().stepKey).toBe('c'))
  })
})

describe('модальное окно, не связанное с якорем', () => {
  const steps: TourStep<null>[] = [
    { ...base, key: 'w', title: 'Ждём', kind: 'wait' },
    { ...base, key: 'o', title: 'Вне окна', kind: 'story', anchor: 'outside' },
  ]
  const windowed = (
    <>
      <Button data-tour="outside">Снаружи</Button>
      <Dialog open>
        <DialogContent title="Окно">
          <Button>В окне</Button>
        </DialogContent>
      </Dialog>
    </>
  )

  it('якоря нет: карточка внутри открытого окна, без затемнения и перехватчиков', async () => {
    mount(steps, null, windowed)
    await wait(50)
    act(() => startTour('w'))
    const card = await screen.findByRole('dialog', { name: 'Ждём' })
    const modal = screen.getByRole('dialog', { name: 'Окно' })
    expect(modal).toContainElement(card)
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(0)
    expect(card.closest('[aria-hidden="true"]')).toBeNull()
  })

  it('якорь вне открытого окна: карточка тоже внутри окна, затемнения нет', async () => {
    mount(steps, null, windowed)
    await wait(50)
    act(() => startTour('o'))
    const card = await screen.findByRole('dialog', { name: 'Вне окна' })
    expect(screen.getByRole('dialog', { name: 'Окно' })).toContainElement(card)
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(0)
  })
})

describe('allowOutside и затемнение', () => {
  it('allowOutside снимает перехватчики кликов, затемнение остаётся', async () => {
    const steps: TourStep<null>[] = [
      { ...base, key: 'a', title: 'A', kind: 'story', anchor: 'a1', allowOutside: true },
    ]
    mount(steps, null, <Button data-tour="a1">Якорь</Button>)
    act(() => startTour('a'))
    await screen.findByRole('dialog', { name: 'A' })
    expect(document.querySelectorAll('[data-tour-blocker]')).toHaveLength(0)
    expect(document.querySelector('svg rect.fill-scrim')).toBeInTheDocument()
    expect(document.querySelector('svg')).not.toHaveClass('invisible')
  })

  it('слой тура и центральная карточка лежат у корня документа', async () => {
    const steps: TourStep<null>[] = [{ ...base, key: 'f', title: 'Финал', kind: 'finish' }]
    renderUi(
      <div id="isolated">
        <TourHost steps={steps} context={null} persistence={persistence()} restore={false} />
      </div>,
    )
    act(() => startTour('f'))
    const card = await screen.findByRole('dialog', { name: 'Финал' })
    expect(document.getElementById('isolated')).not.toContainElement(card)
    const layer = document.querySelector('[data-tour-layer].fixed')
    expect(layer?.parentElement).toBe(document.body)
  })
})

describe('условия шага', () => {
  it('doneWhen завершает шаг-действие по состоянию контекста', async () => {
    const steps: TourStep<{ done: boolean }>[] = [
      {
        ...base,
        key: 'a',
        title: 'A',
        kind: 'action',
        anchor: 'a1',
        doneWhen: (ctx) => ctx.done,
      },
      { ...base, key: 'c', title: 'C', kind: 'finish' },
    ]
    const ui = (done: boolean) => (
      <>
        <Button data-tour="a1">Якорь</Button>
        <TourHost
          steps={steps}
          context={{ done }}
          persistence={persistence()}
          restore={false}
          anchorTimeoutMs={150}
        />
      </>
    )
    const { rerender } = renderUi(ui(false))
    act(() => startTour('a'))
    await screen.findByRole('dialog', { name: 'A' })
    rerender(ui(true))
    await waitFor(() => expect(useTourStore.getState().stepKey).toBe('c'))
  })

  it('skipIf посреди шага пропускает его', async () => {
    const steps: TourStep<{ skip: boolean }>[] = [
      { ...base, key: 'a', title: 'A', kind: 'story', anchor: 'a1', skipIf: (ctx) => ctx.skip },
      { ...base, key: 'c', title: 'C', kind: 'finish' },
    ]
    const ui = (skip: boolean) => (
      <>
        <Button data-tour="a1">Якорь</Button>
        <TourHost steps={steps} context={{ skip }} persistence={persistence()} restore={false} />
      </>
    )
    const { rerender } = renderUi(ui(false))
    act(() => startTour('a'))
    await screen.findByRole('dialog', { name: 'A' })
    rerender(ui(true))
    await waitFor(() => expect(useTourStore.getState().stepKey).toBe('c'))
  })

  it('ticks пересчитывают view по времени, prepare вызывается и откатывается', async () => {
    const cleanup = vi.fn()
    const prepare = vi.fn(() => cleanup)
    const steps: TourStep<null>[] = [
      {
        ...base,
        key: 'a',
        title: 'A',
        kind: 'wait',
        prepare,
        ticks: [80],
        view: ({ elapsedMs }) =>
          elapsedMs >= 80 ? { title: 'Долго', tone: 'waiting' } : undefined,
      },
      { ...base, key: 'c', title: 'C', kind: 'finish' },
    ]
    mount(steps, null)
    act(() => startTour('a'))
    await screen.findByRole('dialog', { name: 'A' })
    expect(prepare).toHaveBeenCalledOnce()
    expect(await screen.findByRole('dialog', { name: 'Долго' })).toBeInTheDocument()
    expect(cleanup).not.toHaveBeenCalled()
    // уход со шага откатывает prepare
    act(() => useTourStore.getState().enter('c', ['a']))
    expect(cleanup).toHaveBeenCalledOnce()
  })

  it('неизвестный ключ шага останавливает тур', async () => {
    mount([{ ...base, key: 'a', title: 'A', kind: 'story' }], null)
    act(() => startTour('нет-такого'))
    await waitFor(() => expect(useTourStore.getState().status).toBe('idle'))
  })
})

describe('пауза', () => {
  it('на паузе сигналы не двигают тур', async () => {
    const steps: TourStep<null>[] = [
      {
        ...base,
        key: 'a',
        title: 'A',
        kind: 'action',
        anchor: 'a1',
        until: (signal) => signal.type === 'share.created',
      },
      { ...base, key: 'c', title: 'C', kind: 'finish' },
    ]
    mount(steps, null, <Button data-tour="a1">Якорь</Button>)
    act(() => startTour('a'))
    await screen.findByRole('dialog', { name: 'A' })
    act(() => useTourStore.getState().setPaused(true))
    act(() => emitOnboardingSignal({ type: 'share.created' }))
    expect(useTourStore.getState().stepKey).toBe('a')
    expect(useTourStore.getState().paused).toBe(true)
    expect(
      await screen.findByRole('region', { name: 'Обучение приостановлено' }),
    ).toBeInTheDocument()
  })
})

describe('защита слоёв: нажатие в слое обучения не закрывает', () => {
  // Radix подписывается на «клик снаружи» после первого такта.
  const settle = () => wait(20)

  function Layer() {
    return (
      <div data-tour-layer="">
        <Button>Далее</Button>
      </div>
    )
  }
  const layerButton = () =>
    within(document.querySelector('[data-tour-layer]') as HTMLElement).getByRole('button', {
      name: 'Далее',
      hidden: true,
    })

  it('Sheet', async () => {
    const onOpenChange = vi.fn()
    renderUi(
      <>
        <Sheet open onOpenChange={onOpenChange}>
          <SheetContent title="Панель">Тело</SheetContent>
        </Sheet>
        <Layer />
      </>,
    )
    await settle()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.pointer({ target: layerButton(), keys: '[MouseLeft]' })
    expect(onOpenChange).not.toHaveBeenCalled()
  })

  it('Popover', async () => {
    const onOpenChange = vi.fn()
    renderUi(
      <>
        <Popover open onOpenChange={onOpenChange}>
          <PopoverTrigger asChild>
            <Button>Открыть</Button>
          </PopoverTrigger>
          <PopoverContent>Содержимое</PopoverContent>
        </Popover>
        <Layer />
      </>,
    )
    await settle()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.pointer({ target: layerButton(), keys: '[MouseLeft]' })
    expect(onOpenChange).not.toHaveBeenCalled()
  })

  it('DropdownMenu', async () => {
    const onOpenChange = vi.fn()
    renderUi(
      <>
        <DropdownMenu open onOpenChange={onOpenChange}>
          <DropdownMenuTrigger asChild>
            <Button>Меню</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem>Пункт</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Layer />
      </>,
    )
    await settle()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.pointer({ target: layerButton(), keys: '[MouseLeft]' })
    expect(onOpenChange).not.toHaveBeenCalled()
  })
})

describe('маршрут шага, который появляется позже', () => {
  it('переходит на экран, когда id проекта приходит в контексте после входа в шаг', async () => {
    const steps: TourStep<{ id: string | null }>[] = [
      {
        ...base,
        key: 'a',
        title: 'A',
        kind: 'story',
        route: (ctx) => (ctx.id ? { to: '/p/$id', params: { id: ctx.id } } : undefined),
      },
    ]
    let setId: (id: string | null) => void = () => {}
    function Host() {
      const [id, set] = useState<string | null>(null)
      setId = set
      return (
        <>
          <Outlet />
          <TourHost steps={steps} context={{ id }} persistence={persistence()} restore={false} />
        </>
      )
    }
    const root = createRootRoute({ component: Host })
    const home = createRoute({
      getParentRoute: () => root,
      path: '/',
      component: () => <div>Дом</div>,
    })
    const project = createRoute({
      getParentRoute: () => root,
      path: '/p/$id',
      component: () => <div>Проект</div>,
    })
    const router = createRouter({
      routeTree: root.addChildren([home, project]),
      history: createMemoryHistory({ initialEntries: ['/'] }),
    })
    render(<RouterProvider router={router} />)
    await screen.findByText('Дом')
    act(() => startTour('a'))
    await wait(50)
    expect(router.state.location.pathname).toBe('/')
    act(() => setId('42'))
    await waitFor(() => expect(router.state.location.pathname).toBe('/p/42'))
    expect(useTourStore.getState().paused).toBe(false)
  })
})
