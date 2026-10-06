import type Canvas from 'diagram-js/lib/core/Canvas'
import type EventBus from 'diagram-js/lib/core/EventBus'
import type { EventBusEventCallback } from 'diagram-js/lib/core/EventBus'
import type { DiagramSimulation, SimulationOption } from '../types'

export interface PlaybackElement {
  id: string
  type: string
  businessObject?: { name?: string; $type?: string }
  parent?: PlaybackElement
  target?: PlaybackElement
  outgoing?: PlaybackElement[]
}
interface Scope {
  element: PlaybackElement
  parent: Scope | null
  running: boolean
  active: boolean
}
interface Subscription {
  element?: PlaybackElement
  event: { type: string; boundary?: boolean }
  scope: Scope
}
interface PublicSubscription extends Subscription {
  element: PlaybackElement
}
interface Animation {
  element: PlaybackElement
  pause(): void
}
interface Simulator {
  findScopes(filter: (scope: Scope) => boolean): Scope[]
  findSubscriptions(filter: (subscription: Subscription) => boolean): Subscription[]
  trigger(subscription: Pick<Subscription, 'event' | 'scope'>): unknown
  signal(context: {
    element: PlaybackElement
    startEvent?: PlaybackElement
    startNodes?: PlaybackElement[]
  }): unknown
  getConfig(element: PlaybackElement): { activeOutgoing?: PlaybackElement }
}
interface PauseSimulation {
  isPaused: boolean
  pause(): void
  unpause(): void
}
export interface PlaybackServices {
  get<T>(name: string): T
}

export const EMPTY_SIMULATION: DiagramSimulation = {
  active: false,
  paused: false,
  status: 'ready',
  starts: [],
  choices: [],
  waiting: [],
}

function option(element: PlaybackElement): SimulationOption {
  return { id: element.id, label: element.businessObject?.name || element.id }
}

/** Только подписки корневого процесса: события вложенных процессов запускаются его семантикой. */
export function isProcessStart(subscription: Subscription): subscription is PublicSubscription {
  return (
    Boolean(subscription.element) &&
    !subscription.scope.parent &&
    !subscription.scope.running &&
    ['bpmn:Process', 'bpmn:Participant'].includes(subscription.scope.element.type)
  )
}

export function sequenceChoices(element: PlaybackElement): PlaybackElement[] {
  return (element.outgoing ?? []).filter((flow) => flow.type === 'bpmn:SequenceFlow')
}

/** Управляет штатным Simulator. Порядок, AND join и завершение остаются у библиотеки. */
export class Playback {
  private active = false
  private started = false
  private disposed = false
  private scheduled = false
  private message: string | undefined
  private choiceQueue: PlaybackElement[] = []
  private highlighted = new Set<string>()
  private lastStart: string | undefined
  private readonly disposers: Array<() => void> = []

  private readonly services: PlaybackServices
  private readonly onChange: (state: DiagramSimulation) => void
  private readonly onStart: () => void

  constructor(
    services: PlaybackServices,
    onChange: (state: DiagramSimulation) => void,
    onStart: () => void,
  ) {
    this.services = services
    this.onChange = onChange
    this.onStart = onStart
    const bus = services.get<EventBus>('eventBus')
    const listen = <T>(event: string, handler: (event: T) => void) => {
      bus.on(event, 250, handler as EventBusEventCallback<unknown>)
      this.disposers.push(() => bus.off(event, handler as EventBusEventCallback<unknown>))
    }
    listen('tokenSimulation.toggleMode', (event: { active: boolean }) => {
      this.active = event.active
      this.started = false
      this.choiceQueue = []
      this.message = undefined
      this.schedule()
    })
    listen('tokenSimulation.resetSimulation', () => {
      this.started = false
      this.choiceQueue = []
      this.message = undefined
      this.schedule()
    })
    listen('tokenSimulation.simulator.createScope', () => {
      if (this.active && !this.started) {
        this.started = true
        this.onStart()
      }
      this.schedule()
    })
    listen('tokenSimulation.animationCreated', (event: { animation: Animation }) => {
      const gateway = event.animation.element.target
      if (gateway?.type === 'bpmn:ExclusiveGateway' && sequenceChoices(gateway).length > 1) {
        if (!this.choiceQueue.includes(gateway)) this.choiceQueue.push(gateway)
        // animationCreated приходит до animation.play(): пауза после выхода из текущего стека.
        queueMicrotask(() => {
          if (this.disposed || !this.active || !this.choiceQueue.length) return
          this.services.get<PauseSimulation>('pauseSimulation').pause()
          event.animation.pause()
          this.schedule()
        })
      }
      this.schedule()
    })
    for (const event of [
      'tokenSimulation.simulator.tick',
      'tokenSimulation.playSimulation',
      'tokenSimulation.pauseSimulation',
    ])
      listen(event, () => this.schedule())
  }

  private simulator(): Simulator {
    return this.services.get<Simulator>('simulator')
  }

  private starts(): PublicSubscription[] {
    return this.simulator().findSubscriptions(isProcessStart).filter(isProcessStart)
  }

  private startOptions(): SimulationOption[] {
    const options = this.starts().map((item) => ({
      id: item.element.id,
      label: `${item.scope.element.businessObject?.name || item.scope.element.id} / ${option(item.element).label}`,
    }))
    return options.map((item) => ({
      ...item,
      label:
        options.filter((other) => other.label === item.label).length > 1
          ? `${item.label} (${item.id})`
          : item.label,
    }))
  }

  /** Единственный старт запускается сразу; несколько остаются явным выбором пользователя. */
  autoStart(): void {
    const starts = this.starts()
    if (starts.length === 1) this.start(starts[0]?.element.id)
    else if (!starts.length) {
      this.message = 'В схеме нет поддерживаемого начального события.'
      this.schedule()
    }
  }

  start(id?: string): void {
    if (!this.active) return
    if (this.started) {
      if (this.choiceQueue.length) return
      this.services.get<PauseSimulation>('pauseSimulation').unpause()
      this.schedule()
      return
    }
    const starts = this.starts()
    const selected =
      starts.find((item) => item.element.id === (id ?? this.lastStart)) ??
      (starts.length === 1 ? starts[0] : undefined)
    if (!selected) return
    this.lastStart = selected.element.id
    this.message = undefined
    try {
      // Root trigger сопоставляет name/iref и при одинаковых именах запускает несколько стартов.
      // Используем публичный signal с точным startEvent, как callback initializeRootScopes.
      this.simulator().signal({
        element: selected.scope.element,
        ...(selected.element.type === 'bpmn:StartEvent'
          ? { startEvent: selected.element }
          : { startNodes: [selected.element] }),
      })
    } catch {
      this.message =
        'Это событие не поддерживается воспроизведением. Проверьте тип события в схеме.'
    }
    this.schedule()
  }

  pause(): void {
    if (this.active) this.services.get<PauseSimulation>('pauseSimulation').pause()
    this.schedule()
  }

  reset(): void {
    this.services.get<{ resetSimulation(): void }>('resetSimulation').resetSimulation()
  }

  choose(id: string): void {
    const gateway = this.choiceQueue[0]
    if (!gateway || !sequenceChoices(gateway).some((flow) => flow.id === id)) return
    const settings = this.services.get<{ setSequenceFlow(element: PlaybackElement): void }>(
      'exclusiveGatewaySettings',
    )
    // Используем штатное конфигурирование шлюза и его подсветку, не заменяя BPMN behavior.
    for (let i = 0; i < sequenceChoices(gateway).length; i += 1) {
      if (this.simulator().getConfig(gateway).activeOutgoing?.id === id) break
      settings.setSequenceFlow(gateway)
    }
    this.choiceQueue.shift()
    if (!this.choiceQueue.length) this.services.get<PauseSimulation>('pauseSimulation').unpause()
    this.schedule()
  }

  trigger(id: string): void {
    const subscription = this.waitingSubscriptions().find((item) => item.element.id === id)
    if (!subscription) return
    this.simulator().trigger(subscription)
    this.services.get<PauseSimulation>('pauseSimulation').unpause()
    this.schedule()
  }

  private waitingSubscriptions(): PublicSubscription[] {
    return this.simulator()
      .findSubscriptions(() => true)
      .filter((item): item is PublicSubscription =>
        Boolean(
          item.element &&
            item.scope.running &&
            !item.event.boundary &&
            item.element.type !== 'bpmn:StartEvent' &&
            (item.scope.element === item.element ||
              ['bpmn:IntermediateCatchEvent', 'bpmn:ReceiveTask'].includes(item.element.type)),
        ),
      )
  }

  private schedule(): void {
    if (this.scheduled || this.disposed) return
    this.scheduled = true
    queueMicrotask(() => {
      this.scheduled = false
      if (!this.disposed) this.publish()
    })
  }

  private publish(): void {
    const scopes = this.active ? this.simulator().findScopes((scope) => scope.running) : []
    const canvas = this.services.get<Canvas>('canvas')
    const next = new Set(scopes.filter((scope) => scope.parent).map((scope) => scope.element.id))
    for (const id of this.highlighted)
      if (!next.has(id)) canvas.removeMarker(id, 'de-playback-active')
    for (const id of next) if (!this.highlighted.has(id)) canvas.addMarker(id, 'de-playback-active')
    this.highlighted = next
    const gateway = this.choiceQueue[0]
    const waiting = this.active && this.started ? this.waitingSubscriptions() : []
    const status = !this.started
      ? 'ready'
      : !scopes.length
        ? 'completed'
        : gateway || waiting.length
          ? 'waiting'
          : this.services.get<PauseSimulation>('pauseSimulation').isPaused
            ? 'paused'
            : 'playing'
    const rootStarts = new Set(this.starts().map((item) => item.element.id))
    for (const overlay of canvas
      .getContainer()
      .querySelectorAll<HTMLElement>('.djs-overlays[data-container-id]')) {
      overlay.classList.toggle(
        'de-playback-root-start',
        this.active && rootStarts.has(overlay.dataset.containerId ?? ''),
      )
    }
    this.onChange({
      active: this.active,
      paused: this.active && this.services.get<PauseSimulation>('pauseSimulation').isPaused,
      status,
      starts: this.active ? this.startOptions() : [],
      choices: gateway ? sequenceChoices(gateway).map(option) : [],
      choiceLabel: gateway ? option(gateway).label : undefined,
      waiting: [
        ...new Map(waiting.map((item) => [item.element.id, option(item.element)])).values(),
      ],
      message: this.message,
    })
  }

  destroy(): void {
    this.disposed = true
    for (const dispose of this.disposers) dispose()
  }
}
