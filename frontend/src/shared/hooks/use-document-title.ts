import { useEffect } from 'react'

const APP = 'Архитектор BPMN'

/** Заголовок вкладки: «Проекты — Архитектор BPMN». Без аргумента — только название продукта. */
export function useDocumentTitle(title?: string) {
  useEffect(() => {
    document.title = title ? `${title} — ${APP}` : APP
  }, [title])
}
