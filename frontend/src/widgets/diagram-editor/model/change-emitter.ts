/**
 * Отложенная выдача изменений схемы наружу.
 *
 * bpmn-js шлёт `commandStack.changed` на каждый шаг перетаскивания, правку подписи, undo/redo
 * и на очистку стека при импорте. Наружу отдаём XML не чаще раза в `delay` мс,
 * пропускаем импорт (`trigger: 'clear'`) и не шлём одинаковый XML дважды —
 * например, если правку сразу отменили.
 */

/** Триггеры `commandStack.changed`, которые означают правку пользователя. */
const EDIT_TRIGGERS = new Set(['execute', 'undo', 'redo'])

export interface ChangeEmitterOptions {
  delay: number
  /** Сериализует текущую схему (обычно `saveXML({ format: true })`). */
  serialize: () => Promise<string>
  onChange: (xml: string) => void
  /** Сразу отмечает правку до выгрузки XML; после ошибки остаётся true до отмены/новой выгрузки. */
  onChangePending?: (pending: boolean) => void
  onError?: (error: unknown) => void
}

export interface ChangeEmitter {
  /** Событие стека команд. Без триггера считается правкой. */
  notify(trigger?: string): void
  /** Задаёт XML, с которым сравниваются изменения (после импорта). */
  setBaseline(xml: string): void
  /** Немедленно выдать отложенное изменение, если оно есть. */
  flush(): Promise<void>
  /** Забыть отложенное изменение (например, перед новым импортом). */
  cancel(): void
  hasPending(): boolean
}

export function createChangeEmitter(options: ChangeEmitterOptions): ChangeEmitter {
  const { delay, serialize, onChange, onChangePending, onError } = options
  let timer: ReturnType<typeof setTimeout> | undefined
  let baseline: string | undefined
  // Поколение растёт при cancel/setBaseline: результат «устаревшей» сериализации отбрасывается.
  let generation = 0
  let revision = 0
  let pending = false

  function setPending(value: boolean) {
    if (pending === value) return
    pending = value
    onChangePending?.(value)
  }

  async function emit(): Promise<void> {
    timer = undefined
    const started = generation
    const startedRevision = revision
    let xml: string
    try {
      xml = await serialize()
    } catch (error) {
      onError?.(error)
      return
    }
    if (started !== generation) return
    if (xml !== baseline) {
      baseline = xml
      onChange(xml)
    }
    // Новая команда могла прийти, пока saveXML ожидался: её защита ещё нужна.
    if (startedRevision === revision) setPending(false)
  }

  return {
    notify(trigger) {
      if (trigger !== undefined && !EDIT_TRIGGERS.has(trigger)) return
      revision += 1
      setPending(true)
      if (timer !== undefined) clearTimeout(timer)
      timer = setTimeout(() => void emit(), delay)
    },
    setBaseline(xml) {
      generation += 1
      baseline = xml
      setPending(false)
    },
    flush() {
      if (timer === undefined) return Promise.resolve()
      clearTimeout(timer)
      return emit()
    },
    cancel() {
      generation += 1
      if (timer !== undefined) clearTimeout(timer)
      timer = undefined
      setPending(false)
    },
    hasPending() {
      return timer !== undefined
    },
  }
}
