import type Canvas from 'diagram-js/lib/core/Canvas'
import type EventBus from 'diagram-js/lib/core/EventBus'
import { translateSimulationMessage, translateUiText } from './translate'

/**
 * Русификация симуляции токена и счётчика поиска во всплывающем меню.
 *
 * bpmn-js-token-simulation не пользуется сервисом translate: подсказки кнопок зашиты в HTML,
 * сообщения журнала и уведомлений — в код. Поэтому:
 *  1. оборачиваем методы журнала и уведомлений и переводим `text` до показа;
 *  2. наблюдаем за HTML-интерфейсом внутри холста и переводим подсказки (title, aria-label)
 *     и несколько статичных подписей. Текст самой схемы (SVG) не трогаем никогда.
 */

const ATTRIBUTES = ['title', 'aria-label']
/** Где разрешено переводить текстовые узлы: только служебные подписи, не названия элементов. */
const TEXT_SCOPES = '.bts-header, .bts-entry.placeholder, .bts-toggle-mode, .djs-popup-search-count'

interface Injector {
  get<T = unknown>(name: string, strict?: boolean): T | null
}

type TextOptions = { text?: unknown } | undefined

/** Методы сервисов симуляции, в аргументах которых приходит `{ text }`, и номер этого аргумента. */
const TEXT_METHODS: ReadonlyArray<[service: string, method: string, argument: number]> = [
  ['log', 'log', 0],
  ['notifications', 'showNotification', 0],
  ['elementNotifications', 'addElementNotification', 1],
]

function translateOptions(options: TextOptions): TextOptions {
  if (!options || typeof options.text !== 'string') return options
  return { ...options, text: translateSimulationMessage(options.text) }
}

function wrapTextMethods(injector: Injector): void {
  for (const [name, method, argument] of TEXT_METHODS) {
    const service = injector.get<Record<string, unknown>>(name, false)
    const original = service?.[method]
    if (!service || typeof original !== 'function') continue
    service[method] = (...args: unknown[]) => {
      args[argument] = translateOptions(args[argument] as TextOptions)
      return original.apply(service, args)
    }
  }
}

function translateAttributes(element: Element): void {
  for (const attribute of ATTRIBUTES) {
    const value = element.getAttribute(attribute)
    const translated = value ? translateUiText(value) : undefined
    if (translated && translated !== value) element.setAttribute(attribute, translated)
  }
}

function translateText(node: Text): void {
  const parent = node.parentElement
  if (!parent || parent.closest('svg') || !parent.closest(TEXT_SCOPES)) return
  const raw = node.nodeValue ?? ''
  const trimmed = raw.trim()
  const translated = trimmed ? translateUiText(trimmed) : undefined
  if (translated && translated !== trimmed) node.nodeValue = raw.replace(trimmed, translated)
}

function translateTree(node: Node): void {
  if (node.nodeType === Node.TEXT_NODE) {
    translateText(node as Text)
    return
  }
  if (!(node instanceof Element)) return
  translateAttributes(node)
  for (const element of node.querySelectorAll('[title], [aria-label]')) translateAttributes(element)
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) translateText(walker.currentNode as Text)
}

/** Переводит интерфейс внутри `root` сейчас и при каждом изменении разметки. */
export function localizeDom(root: HTMLElement): MutationObserver {
  translateTree(root)
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'attributes') translateAttributes(record.target as Element)
      else if (record.type === 'characterData') translateTree(record.target)
      else record.addedNodes.forEach(translateTree)
    }
  })
  observer.observe(root, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRIBUTES,
  })
  return observer
}

function SimulationLocalization(eventBus: EventBus, canvas: Canvas, injector: Injector) {
  let observer: MutationObserver | undefined
  wrapTextMethods(injector)
  eventBus.on('diagram.init', () => {
    observer = localizeDom(canvas.getContainer())
  })
  eventBus.on('diagram.destroy', () => observer?.disconnect())
}

SimulationLocalization.$inject = ['eventBus', 'canvas', 'injector']

export const SimulationLocalizationModule = {
  __init__: ['simulationLocalization'],
  simulationLocalization: ['type', SimulationLocalization],
}
