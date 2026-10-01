import type { Ref, RefCallback } from 'react'

/** Объединяет несколько ref в один (нужно, когда компонент и вызывающий код держат один узел). */
export function mergeRefs<T>(...refs: Array<Ref<T> | undefined>): RefCallback<T> {
  return (node) => {
    for (const ref of refs) {
      if (typeof ref === 'function') ref(node)
      else if (ref) ref.current = node
    }
  }
}
