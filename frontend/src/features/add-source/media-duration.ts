/** Длительность и видеодорожка записи из метаданных браузера (до загрузки на сервер). */
export interface MediaFileInfo {
  durationSec: number
  hasVideo: boolean
}

const VIDEO_EXTENSIONS = /\.(mp4|mov|mkv|webm)$/i

/** Сколько ждём метаданные, прежде чем честно признать длительность неизвестной. */
export const MEDIA_METADATA_TIMEOUT_MS = 4000

export function mediaFileInfo(
  file: File,
  createElement: (tag: 'audio' | 'video') => HTMLMediaElement = (tag) =>
    document.createElement(tag) as HTMLMediaElement,
  timeoutMs = MEDIA_METADATA_TIMEOUT_MS,
): Promise<MediaFileInfo> {
  const hasVideoByType = file.type.startsWith('video/') || VIDEO_EXTENSIONS.test(file.name)
  return new Promise((resolve) => {
    const element = createElement(hasVideoByType ? 'video' : 'audio')
    const url = URL.createObjectURL(file)
    let settled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const finish = (info: MediaFileInfo) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      URL.revokeObjectURL(url)
      element.onloadedmetadata = null
      element.onerror = null
      resolve(info)
    }
    timer = setTimeout(() => finish({ durationSec: 0, hasVideo: hasVideoByType }), timeoutMs)
    element.preload = 'metadata'
    element.onloadedmetadata = () =>
      finish({
        durationSec:
          Number.isFinite(element.duration) && element.duration > 0 ? element.duration : 0,
        hasVideo: hasVideoByType,
      })
    element.onerror = () => finish({ durationSec: 0, hasVideo: hasVideoByType })
    element.src = url
  })
}
