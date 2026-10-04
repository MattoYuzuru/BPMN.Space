import { useEffect } from 'react'

/**
 * Временный `<meta name=… content=…>` в `<head>`, пока компонент смонтирован. Нужен страницам с
 * секретом в адресе (`/share/<токен>`): `referrer` не даёт утечь адресу во внешние запросы,
 * `robots` просит не индексировать. При размонтировании тег убирается, прежний возвращается.
 */
export function useDocumentMeta(name: string, content: string) {
  useEffect(() => {
    const previous = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
    const tag = document.createElement('meta')
    tag.name = name
    tag.content = content
    tag.dataset.temporary = ''
    previous?.remove()
    document.head.append(tag)
    return () => {
      tag.remove()
      if (previous) document.head.append(previous)
    }
  }, [name, content])
}
