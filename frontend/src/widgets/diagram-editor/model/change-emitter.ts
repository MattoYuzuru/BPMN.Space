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
  const { delay, serialize, onChange, onError } = options
  let timer: ReturnType<typeof setTimeout> | undefined
  let baseline: string | undefined
  // Поколение растёт при cancel/setBaseline: результат «устаревшей» сериализации отбрасывается.
  let generation = 0

  async function emit(): Promise<void> {
    timer = undefined
    const started = generation
    let xml: string
    try {
      xml = await serialize()
    } catch (error) {
      onError?.(error)
      return
    }
    if (started !== generation || xml === baseline) return
    baseline = xml
    onChange(xml)
  }

  return {
    notify(trigger) {
      if (trigger !== undefined && !EDIT_TRIGGERS.has(trigger)) return
      if (timer !== undefined) clearTimeout(timer)
      timer = setTimeout(() => void emit(), delay)
    },
    setBaseline(xml) {
      generation += 1
      baseline = xml
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
    },
    hasPending() {
      return timer !== undefined
    },
  }
}
